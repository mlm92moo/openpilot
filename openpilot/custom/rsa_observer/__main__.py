"""Observation-only RSA capture. Run with --help in the selected openpilot environment."""
import argparse
import math
from pathlib import Path
import sys

from .core import Config, NS, Observer
from .compatibility import verify_runtime
from .inputs import json_events, live_events, rlog_events, validate_rlog_paths
from .output import JsonWriter, OutputLimit


def argument_parser():
  parser = argparse.ArgumentParser(description=__doc__)
  commands = parser.add_subparsers(dest="mode", required=True)
  for mode in ("jsonl", "rlog", "live"):
    command = commands.add_parser(mode)
    command.add_argument("--output", type=Path, required=True, help="new JSONL file; refuses overwrite")
    command.add_argument("--bus", type=int, default=2)
    command.add_argument("--persistence", type=float, default=.5, help="provisional diagnostic seconds")
    command.add_argument("--minimum-events", type=int, default=3)
    command.add_argument("--maximum-gap", type=float, default=1.5)
    command.add_argument("--stale", type=float, default=3)
    command.add_argument("--max-mib", type=int, default=64, help="stop at this bounded output size")
    command.add_argument("--quiet", action="store_true")
    if mode == "live":
      command.add_argument("--duration", type=float, default=600, help="capture seconds, at most 3600")
    elif mode == "jsonl":
      command.add_argument("input", type=Path)
    else:
      command.add_argument("inputs", nargs="+", type=Path, help="local full rlogs in chronological segment order")
  return parser


def run(events, observer, writer, mode, quiet=False):
  last_status_ns = None
  last_signature = None
  status = "complete"
  error = None
  code = 0
  writer.write({**observer.metadata(), "input_mode": mode})
  try:
    for event, now_ns in events:
      rows = observer.observe(event, now_ns)
      for row in rows:
        writer.write(row)
      heartbeat_due = last_status_ns is None or now_ns - last_status_ns >= NS
      if rows or heartbeat_due:
        snapshot = observer.status(now_ns)
        signature = (snapshot["state"], snapshot["observed_primary_mps"], snapshot["persistent_primary_mps"])
        if heartbeat_due or signature != last_signature:
          writer.write(snapshot)
          last_status_ns = now_ns
          last_signature = signature
          if not quiet:
            speed = snapshot["observed_primary_mps"]
            display = "unavailable" if speed is None else f"{speed / .44704:.1f} mph / {speed * 3.6:.1f} km/h"
            persistent = snapshot["persistent_primary_mps"] is not None
            print(f"RSA observation: {display}; {snapshot['state']}; persistent={persistent}; age={snapshot['rsa1_age_s']}; control eligibility unverified", file=sys.stderr)
  except OutputLimit as exc:
    status, error, code = "output_limit", str(exc), 2
  except KeyboardInterrupt:
    status, code = "interrupted", 130
  except Exception as exc:
    status, error, code = "error", f"{type(exc).__name__}: {exc}", 1
  final_snapshot = observer.status(observer.last_clock_ns) if observer.last_clock_ns is not None else None
  writer.write({"type": "end", "status": status, "error": error, "snapshot": final_snapshot,
                "meaning": "complete means input iteration finished, not that a route or CAN capture is complete"}, final=True)
  if error:
    print(error, file=sys.stderr)
  return code


def main(argv=None, parser_factory=None):
  parser = argument_parser()
  args = parser.parse_args(argv)
  try:
    config = Config(args.bus, args.persistence, args.minimum_events, args.maximum_gap, args.stale)
    if not 1 <= args.max_mib <= 1024:
      raise ValueError("max-mib must be 1..1024")
    inputs = []
    if args.mode == "live":
      if not math.isfinite(args.duration) or not 0 < args.duration <= 3600:
        raise ValueError("duration must be positive and <= 3600 seconds")
      events = live_events(args.duration)
    elif args.mode == "jsonl":
      inputs = [args.input.resolve(strict=True)]
      events = json_events(inputs[0])
    else:
      inputs = validate_rlog_paths(args.inputs)
      events = rlog_events(inputs)
    if args.output.resolve() in inputs:
      raise ValueError("output must not be an input file")
    if parser_factory is None:
      verify_runtime(args.mode)
    observer = Observer(config, parser_factory)
    writer = JsonWriter(args.output, args.max_mib * 1024 * 1024)
  except (ValueError, OSError, ImportError) as exc:
    parser.error(str(exc))
  try:
    return run(events, observer, writer, args.mode, args.quiet)
  finally:
    events.close()
    writer.close()


if __name__ == "__main__":
  raise SystemExit(main())
