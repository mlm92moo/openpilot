"""Timestamped observations and diagnostic persistence; no accepted/applied cap."""
from collections import Counter, deque
from dataclasses import asdict, dataclass
import math
from pathlib import Path

RSA1, RSA2 = 0x489, 0x48A
NS = 1_000_000_000


@dataclass(frozen=True)
class Config:
  bus: int = 2
  persistence_s: float = 0.5
  minimum_events: int = 3
  # Corolla RSA1 arrives at roughly 1 Hz. Keep a margin for normal CAN
  # scheduling jitter, while retaining the 3-second freshness deadline.
  maximum_gap_s: float = 1.5
  stale_s: float = 3.0
  minimum_kph: float = 5.0
  maximum_kph: float = 160.0

  def __post_init__(self):
    if type(self.bus) is not int or not 0 <= self.bus <= 3:
      raise ValueError("bus must be 0..3")
    if type(self.minimum_events) is not int or self.minimum_events < 2:
      raise ValueError("minimum_events must be an integer >= 2")
    for key in ("persistence_s", "maximum_gap_s", "stale_s", "minimum_kph", "maximum_kph"):
      value = getattr(self, key)
      if type(value) not in (int, float) or not math.isfinite(value) or value <= 0:
        raise ValueError(f"{key} must be finite and positive")
    if self.maximum_gap_s > self.stale_s or self.minimum_kph >= self.maximum_kph:
      raise ValueError("invalid gap/staleness or speed range")


@dataclass(frozen=True)
class Frame:
  address: int
  bus: int
  data: bytes


@dataclass(frozen=True)
class Event:
  t_ns: int
  frames: tuple[Frame, ...]
  valid: bool = True
  vehicle: dict | None = None

  def __post_init__(self):
    if type(self.t_ns) is not int or not 0 <= self.t_ns <= 2**63 - 1:
      raise ValueError("event timestamp must be a nonnegative signed-64-bit integer")
    if type(self.valid) is not bool:
      raise ValueError("event valid must be boolean")
    for frame in self.frames:
      if type(frame.address) is not int or not 0 <= frame.address <= 0x1FFFFFFF:
        raise ValueError("invalid CAN address")
      if type(frame.bus) is not int or not 0 <= frame.bus <= 255:
        raise ValueError("invalid CAN bus")
      if type(frame.data) is not bytes or len(frame.data) > 64:
        raise ValueError("CAN payload must be bytes of length <= 64")


def normalize(sign, speed, config):
  result = {"speed_mps": None, "raw_speed": speed, "unit": None, "reason": "unsupported_sign"}
  if type(sign) is not int or type(speed) is not int or not 0 <= sign <= 255 or not 0 <= speed <= 255:
    return {**result, "reason": "invalid_encoding"}
  if sign not in (1, 36):
    return {**result, "reason": "no_sign" if sign == 0 else "unsupported_sign"}
  result["unit"] = "km/h" if sign == 1 else "mph"
  if speed == 0:
    return {**result, "reason": "no_numeric_limit"}
  if speed == 255:
    return {**result, "reason": "no_limit_indication"}
  if speed >= 200:
    return {**result, "reason": "blank_number"}
  mps = speed / 3.6 if sign == 1 else speed * 0.44704
  if not config.minimum_kph / 3.6 <= mps <= config.maximum_kph / 3.6:
    return {**result, "reason": "outside_diagnostic_range"}
  return {**result, "speed_mps": mps, "reason": "numeric_observation"}


class Decoder:
  def __init__(self, config, parser_factory=None):
    if parser_factory is None:
      from opendbc.can.parser import CANParser
      parser_factory = CANParser
    self.bus = config.bus
    self.parser = parser_factory(str(Path(__file__).with_name("rsa_observer.dbc")),
                                 [("RSA1", float("nan")), ("RSA2", float("nan"))], self.bus)

  def decode(self, t_ns, frame):
    # Current CANParser does not enforce an exact frame length for these fields.
    if frame.address not in (RSA1, RSA2) or frame.bus != self.bus or len(frame.data) != 8:
      raise ValueError("frame envelope not eligible for RSA decoding")
    updated = self.parser.update([(t_ns, [(frame.address, frame.data, frame.bus)])])
    if frame.address not in updated:
      raise ValueError("parser did not update this frame")
    return {key: int(value) for key, value in self.parser.vl[frame.address].items()}


class Observer:
  def __init__(self, config=Config(), parser_factory=None):
    self.config = config
    self.decoder = Decoder(config, parser_factory)
    self.last_clock_ns = None
    self.last_rsa_ns = {RSA1: None, RSA2: None}
    self.last_payload = {RSA1: None, RSA2: None}
    self.intervals = {RSA1: deque(maxlen=256), RSA2: deque(maxlen=256)}
    self.counters = Counter()
    self.candidate = None
    self.candidate_since_ns = None
    self.candidate_events = 0
    self.primary_mps = None
    self.primary_reason = "unavailable"
    self.primary_fields = None

  def reset_candidate(self, reason):
    self.candidate = None
    self.candidate_since_ns = None
    self.candidate_events = 0
    self.primary_mps = None
    self.primary_reason = reason

  def observe(self, event, now_ns):
    if type(now_ns) is not int or now_ns < 0:
      raise ValueError("now_ns must be a nonnegative integer")
    if self.last_clock_ns is not None and now_ns < self.last_clock_ns:
      raise ValueError("clock reversed; use a new observer for each boot/route")
    self.last_clock_ns = now_ns
    self.counters["input_events_and_ticks"] += 1
    records = [] if event.vehicle is None else [{"type": "vehicle", "t_ns": event.t_ns,
                                                "event_valid": event.valid, **event.vehicle}]
    for frame in event.frames:
      if frame.address not in (RSA1, RSA2):
        continue
      self.counters[f"bus{frame.bus}_{frame.address:x}_frames"] += 1
      row = {"type": "rsa", "t_ns": event.t_ns, "observed_ns": now_ns,
             "address": frame.address, "bus": frame.bus, "data": frame.data.hex(),
             "event_valid": event.valid, "fields": None, "primary": None}
      reason = None
      previous = self.last_rsa_ns[frame.address]
      if frame.bus != self.config.bus:
        reason = "other_bus"
      elif not event.valid:
        reason = "invalid_can_event"
      elif len(frame.data) != 8:
        reason = "invalid_length"
      elif event.t_ns > now_ns:
        reason = "future_timestamp"
      elif previous is not None and event.t_ns <= previous:
        reason = "duplicate_or_reversed_timestamp"
      elif now_ns - event.t_ns > self.config.stale_s * NS:
        reason = "old_queued_event"
      if reason is not None:
        self.counters[reason] += 1
        # Duplicate cached delivery is not evidence of freshness. Any other
        # invalid primary observation breaks diagnostic persistence.
        if frame.bus == self.config.bus and frame.address == RSA1 and reason != "duplicate_or_reversed_timestamp":
          self.reset_candidate(reason)
        elif frame.bus == self.config.bus and frame.address == RSA1 and frame.data != self.last_payload[RSA1]:
          self.reset_candidate("conflicting_duplicate_or_reversed_frame")
        records.append({**row, "reason": reason})
        continue
      fields = self.decoder.decode(event.t_ns, frame)
      self.last_rsa_ns[frame.address] = event.t_ns
      self.last_payload[frame.address] = frame.data
      gap = None if previous is None else event.t_ns - previous
      if gap is not None:
        self.intervals[frame.address].append(gap)
      row.update(fields=fields, reason="decoded")
      if frame.address == RSA1:
        primary = normalize(fields["TSGN1"], fields["SPDVAL1"], self.config)
        row["primary"] = primary
        self.primary_fields = fields
        if primary["speed_mps"] is None:
          self.reset_candidate(primary["reason"])
        else:
          # Sign-status changes break persistence even when the number is equal.
          signature = tuple(fields[k] for k in ("TSGN1", "SPDVAL1", "TSGNGRY1", "TSGNHLT1", "SPLSGN1", "SPLSGN2"))
          if signature != self.candidate or gap is None or gap > self.config.maximum_gap_s * NS:
            self.candidate = signature
            self.candidate_since_ns = event.t_ns
            self.candidate_events = 1
          else:
            self.candidate_events += 1
          self.primary_mps = primary["speed_mps"]
          self.primary_reason = primary["reason"]
      records.append(row)
    return records

  def status(self, now_ns):
    if type(now_ns) is not int or now_ns < 0 or (self.last_clock_ns is not None and now_ns < self.last_clock_ns):
      raise ValueError("invalid status clock")
    self.last_clock_ns = now_ns
    age = None if self.last_rsa_ns[RSA1] is None else (now_ns - self.last_rsa_ns[RSA1]) / NS
    fresh = age is not None and 0 <= age <= self.config.stale_s
    # Persistence is established only by distinct received CAN events, never
    # by merely letting wall time pass after the final received frame.
    persistent = (fresh and self.primary_mps is not None and self.candidate_since_ns is not None
                  and self.candidate_events >= self.config.minimum_events
                  and self.last_rsa_ns[RSA1] - self.candidate_since_ns >= self.config.persistence_s * NS)
    rates = {}
    for addr, intervals in self.intervals.items():
      rates[f"{addr:x}"] = None if not intervals else NS * len(intervals) / sum(intervals)
    return {"type": "status", "t_ns": now_ns, "source": "toyota_rsa", "bus": self.config.bus,
            "rsa1_age_s": age, "rsa1_fresh": fresh,
            "state": self.primary_reason if fresh else ("unavailable" if age is None else "stale"),
            "last_primary_fields": self.primary_fields,
            "observed_primary_mps": self.primary_mps if fresh else None,
            "persistent_primary_mps": self.primary_mps if persistent else None,
            "candidate_events": self.candidate_events,
            "recent_event_rate_hz": rates,
            "control_eligibility": "not_evaluated", "counters": dict(self.counters)}

  def metadata(self):
    from . import VERSION
    from .compatibility import SOURCE_COMMIT, RELEASE_COMMIT, OPENDBC_COMMIT
    return {"type": "metadata", "format": "comma-rsa-observer-v1", "observer_version": VERSION,
            "observation_only": True, "diagnostic_config": asdict(self.config),
            "target_source": SOURCE_COMMIT, "target_release": RELEASE_COMMIT, "target_opendbc": OPENDBC_COMMIT,
            "timing_defaults": "provisional; measure real traffic before choosing control settings"}
