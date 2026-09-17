"""Validate current openpilot GPS messages for gate crossing and recording."""

from dataclasses import dataclass
import math

MAX_HORIZONTAL_ACCURACY_M = 50.0
MAX_BEARING_ACCURACY_DEG = 90.0
MAX_SAMPLE_AGE_S = 1.5


@dataclass(frozen=True)
class ValidatedGPS:
  latitude: float
  longitude: float
  bearing: float
  speed: float
  received_at: float
  sequence: int

  def as_position(self):
    return {"latitude": self.latitude, "longitude": self.longitude, "bearing": self.bearing}


class GPSAdapter:
  def __init__(self, service):
    self.service = service
    self._sequence = None
    self.latest: ValidatedGPS | None = None

  def observe(self, message, now: float) -> ValidatedGPS | None:
    if message is None or message.which() != self.service or not message.valid:
      return None
    sequence = int(message.logMonoTime)
    if sequence == self._sequence:
      return None
    self._sequence = sequence
    sample_time = sequence / 1e9
    if sample_time <= 0 or not -0.1 <= now - sample_time <= MAX_SAMPLE_AGE_S:
      return None
    location = getattr(message, self.service)
    values = (location.latitude, location.longitude, location.bearingDeg, location.speed, location.horizontalAccuracy, location.bearingAccuracyDeg)
    if not location.hasFix or not all(math.isfinite(value) for value in values):
      return None
    if not (-90 <= location.latitude <= 90 and -180 <= location.longitude <= 180):
      return None
    if location.horizontalAccuracy < 0 or location.horizontalAccuracy > MAX_HORIZONTAL_ACCURACY_M:
      return None
    # A stationary receiver often reports an unknown heading. It is useful for
    # displaying position, but it must not be used to create or cross a gate.
    if location.bearingAccuracyDeg < 0 or location.bearingAccuracyDeg > MAX_BEARING_ACCURACY_DEG:
      return None
    self.latest = ValidatedGPS(
      float(location.latitude), float(location.longitude), float(location.bearingDeg) % 360.0, max(0.0, float(location.speed)), sample_time, sequence
    )
    return self.latest

  def current(self, now: float) -> ValidatedGPS | None:
    if self.latest is None or now - self.latest.received_at > MAX_SAMPLE_AGE_S:
      return None
    return self.latest
