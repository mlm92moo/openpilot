"""Read local files or subscribe to CAN. Never publish or send CAN."""
import json
from pathlib import Path
import re
import time
import warnings

from .core import Event, Frame


def json_event(line):
  item = json.loads(line)
  if not isinstance(item, dict) or not {"t_ns", "frames"} <= item.keys() or item.keys() - {"t_ns", "frames", "valid"}:
    raise ValueError("expected t_ns, frames and optional valid")
  if not isinstance(item["frames"], list):
    raise ValueError("frames must be a list")
  frames = []
  for frame in item["frames"]:
    if not isinstance(frame, dict) or frame.keys() != {"address", "bus", "data"}:
      raise ValueError("frame needs address, bus, data")
    if not isinstance(frame["data"], str) or re.fullmatch(r"(?:[0-9a-fA-F]{2}){0,64}", frame["data"]) is None:
      raise ValueError("data must be even-length hexadecimal, up to 64 bytes")
    frames.append(Frame(frame["address"], frame["bus"], bytes.fromhex(frame["data"])))
  return Event(item["t_ns"], tuple(frames), item.get("valid", True))


def json_events(path):
  with Path(path).open(encoding="utf-8") as stream:
    line_number = 0
    while line := stream.readline(1_048_577):
      line_number += 1
      if len(line) > 1_048_576:
        raise ValueError(f"line {line_number}: exceeds 1 MiB")
      try:
        event = json_event(line)
      except (ValueError, TypeError, KeyError) as exc:
        raise ValueError(f"line {line_number}: {exc}") from exc
      yield event, event.t_ns


def cereal_event(message):
  if message.which() == "carParams":
    params = message.carParams
    # A small explicit allowlist; no VIN, device ID, account or full Params dump.
    return Event(int(message.logMonoTime), (), bool(message.valid),
                 {"brand": str(params.brand), "car_fingerprint": str(params.carFingerprint),
                  "openpilot_longitudinal_control": bool(params.openpilotLongitudinalControl)})
  if message.which() != "can":
    # Replay heartbeat in the original log clock, even if CAN has stopped.
    return Event(int(message.logMonoTime), ())
  return Event(int(message.logMonoTime),
               tuple(Frame(int(frame.address), int(frame.src), bytes(frame.dat)) for frame in message.can),
               bool(message.valid))


def validate_rlog_paths(paths):
  resolved = []
  for item in paths:
    path = Path(item).resolve(strict=True)
    if not path.is_file() or path.name not in {"rlog", "rlog.bz2", "rlog.zst"}:
      raise ValueError("supply local rlog, rlog.bz2 or rlog.zst files; qlogs and URLs are not accepted")
    if path in resolved:
      raise ValueError("duplicate rlog path")
    resolved.append(path)
  return resolved


def rlog_events(paths, reader_factory=None):
  paths = validate_rlog_paths(paths)
  if reader_factory is None:
    from openpilot.tools.lib.logreader import LogReader
    reader_factory = LogReader
  # The native reader otherwise warns and returns partial data on corruption.
  # Use one reader per segment so a multi-segment run does not cache all logs.
  previous = None
  for path in paths:
    with warnings.catch_warnings():
      warnings.filterwarnings("error", message="Corrupted events detected", category=RuntimeWarning)
      for message in reader_factory(str(path), sources=[], sort_by_time=True, only_union_types=False):
        event = cereal_event(message)
        if previous is not None and event.t_ns < previous:
          raise ValueError("rlog time reversed across segments; pass chronological segments from one boot")
        previous = event.t_ns
        yield event, event.t_ns


def live_events(duration_s, messaging=None, clock=time.monotonic_ns):
  if messaging is None:
    import openpilot.cereal.messaging as messaging
  # An independent non-conflating subscription preserves intermediate events.
  # One bounded receive at a time also avoids unbounded drain_sock lists.
  sock = messaging.sub_sock("can", conflate=False, timeout=100)
  start = clock()
  try:
    while clock() - start < duration_s * 1_000_000_000:
      message = messaging.recv_one(sock)
      now = clock()
      if message is None:
        yield Event(now, ()), now
      else:
        yield cereal_event(message), now
  finally:
    # msgq releases the subscriber on destruction; there is no required close API.
    del sock
