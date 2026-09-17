"""Directional GPS gate controller, ported from FrogPilot personal-speed-zones-v2."""

from dataclasses import dataclass
import json
import logging
import math
import os

from openpilot.common.constants import CV

try:
  from openpilot.common.swaglog import cloudlog
except ImportError:
  cloudlog = logging.getLogger(__name__)


def log_event(name, **context):
  if hasattr(cloudlog, "event"):
    cloudlog.event(name, **context)
  else:
    cloudlog.info("%s %s", name, context)


CONFIG_PATH = "/data/personal_speed_zones.json"
ACTIVE_ZONE_TIMEOUT_S = 10 * 60
EARTH_RADIUS_M = 6_371_000.0
GPS_ACCURACY_MARGIN_M = 5.0
# comma 4's qcom GPS service is nominally 1 Hz, so allow scheduler jitter.
MAX_GPS_AGE_S = 1.5
MAX_GPS_JUMP_M = 100.0
MAX_GPS_SPEED_MPS = 80.0
MIN_GPS_MOVEMENT_M = 0.5
LOW_SPEED_ACCUMULATION_TIMEOUT_S = 5.0


@dataclass(frozen=True)
class Gate:
  latitude: float
  longitude: float
  bearing: float


@dataclass(frozen=True)
class PersonalSpeedZone:
  zone_id: str
  target: float
  apply_target: bool
  start: Gate
  end: Gate
  corridor_width_m: float
  gate_arm_distance_m: float
  heading_tolerance_deg: float


@dataclass(frozen=True)
class GPSPosition:
  latitude: float
  longitude: float
  bearing: float


def angular_difference(first: float, second: float) -> float:
  return abs((first - second + 180.0) % 360.0 - 180.0)


def local_coordinates(position: GPSPosition, gate: Gate) -> tuple[float, float]:
  latitude_scale = math.pi * EARTH_RADIUS_M / 180.0
  longitude_scale = latitude_scale * math.cos(math.radians(gate.latitude))
  return (position.longitude - gate.longitude) * longitude_scale, (position.latitude - gate.latitude) * latitude_scale


def distance(first: GPSPosition, second: GPSPosition) -> float:
  mean_latitude = math.radians((first.latitude + second.latitude) / 2.0)
  north = math.radians(second.latitude - first.latitude) * EARTH_RADIUS_M
  east = math.radians(second.longitude - first.longitude) * EARTH_RADIUS_M * math.cos(mean_latitude)
  return math.hypot(east, north)


def validate_coordinate(latitude: float, longitude: float) -> None:
  if not math.isfinite(latitude) or not -90.0 <= latitude <= 90.0:
    raise ValueError("latitude must be between -90 and 90")
  if not math.isfinite(longitude) or not -180.0 <= longitude <= 180.0:
    raise ValueError("longitude must be between -180 and 180")


class PersonalSpeedController:
  def __init__(self, config_path: str = CONFIG_PATH, min_target: float = 5.0, max_target: float = 145 * CV.KPH_TO_MS):
    self.config_path = config_path
    self.min_target = min_target
    self.max_target = max_target
    self.active_zone_ids: set[str] = set()
    self.active_zone_started_at: dict[str, object] = {}
    self.applied_target: float | None = None
    self.apply_target = False
    self.target: float | None = None
    self.zones: tuple[PersonalSpeedZone, ...] = ()
    self._observed_file_signature: tuple[int, int, int, int] | None = None
    self._last_sample_time = None
    self._previous_crossing_allowed = False
    self._previous_position: GPSPosition | None = None
    self._previous_time = None

  @staticmethod
  def _parse_gate(zone_config: dict, name: str) -> Gate:
    gate_config = zone_config[name]
    latitude = float(gate_config["latitude"])
    longitude = float(gate_config["longitude"])
    bearing = float(gate_config["bearing"])
    validate_coordinate(latitude, longitude)
    if not math.isfinite(bearing):
      raise ValueError(f"{name} bearing must be finite")
    return Gate(latitude, longitude, bearing % 360.0)

  def _parse_config(self, config: object) -> tuple[bool, tuple[PersonalSpeedZone, ...]]:
    if not isinstance(config, dict) or not isinstance(config.get("zones"), list):
      raise ValueError("configuration must contain a zones list")
    apply_target = config.get("apply_target", False)
    if not isinstance(apply_target, bool):
      raise ValueError("apply_target must be a boolean")
    zones = []
    zone_ids = set()
    for zone_config in config["zones"]:
      if not isinstance(zone_config, dict):
        raise ValueError("each zone must be an object")
      if not zone_config.get("enabled", False):
        continue
      zone_id = str(zone_config["id"]).strip()
      if not zone_id or zone_id in zone_ids:
        raise ValueError("enabled zone IDs must be non-empty and unique")
      target_mph = float(zone_config["target_mph"])
      zone_apply_target = zone_config.get("apply_target", apply_target)
      if not isinstance(zone_apply_target, bool):
        raise ValueError(f"zone {zone_id} apply_target must be a boolean")
      corridor_width_m = float(zone_config["corridor_width_m"])
      gate_arm_distance_m = float(zone_config["gate_arm_distance_m"])
      heading_tolerance_deg = float(zone_config["heading_tolerance_deg"])
      values = target_mph, corridor_width_m, gate_arm_distance_m, heading_tolerance_deg
      if not all(math.isfinite(value) for value in values):
        raise ValueError(f"zone {zone_id} contains a non-finite value")
      if corridor_width_m <= 0 or gate_arm_distance_m <= 0:
        raise ValueError(f"zone {zone_id} distances must be positive")
      if not 0 < heading_tolerance_deg <= 180:
        raise ValueError(f"zone {zone_id} heading tolerance must be in (0, 180]")
      zones.append(
        PersonalSpeedZone(
          zone_id=zone_id,
          target=min(max(target_mph * CV.MPH_TO_MS, self.min_target), self.max_target),
          apply_target=zone_apply_target,
          start=self._parse_gate(zone_config, "start"),
          end=self._parse_gate(zone_config, "end"),
          corridor_width_m=corridor_width_m,
          gate_arm_distance_m=gate_arm_distance_m,
          heading_tolerance_deg=heading_tolerance_deg,
        )
      )
      zone_ids.add(zone_id)
    return apply_target, tuple(zones)

  @staticmethod
  def parse_position(gps_position: object) -> GPSPosition | None:
    if not isinstance(gps_position, dict):
      return None
    try:
      latitude = float(gps_position["latitude"])
      longitude = float(gps_position["longitude"])
      bearing = float(gps_position["bearing"])
      validate_coordinate(latitude, longitude)
    except (KeyError, TypeError, ValueError):
      return None
    if not math.isfinite(bearing):
      return None
    return GPSPosition(latitude, longitude, bearing % 360.0)

  @staticmethod
  def _gate_crossing_fraction(previous: GPSPosition, current: GPSPosition, gate: Gate, zone: PersonalSpeedZone) -> float | None:
    if angular_difference(current.bearing, gate.bearing) > zone.heading_tolerance_deg:
      return None
    previous_east, previous_north = local_coordinates(previous, gate)
    current_east, current_north = local_coordinates(current, gate)
    bearing_radians = math.radians(gate.bearing)
    direction_east, direction_north = math.sin(bearing_radians), math.cos(bearing_radians)
    right_east, right_north = direction_north, -direction_east
    previous_along = previous_east * direction_east + previous_north * direction_north
    current_along = current_east * direction_east + current_north * direction_north
    if not previous_along < 0 <= current_along:
      return None
    previous_cross = previous_east * right_east + previous_north * right_north
    current_cross = current_east * right_east + current_north * right_north
    if max(abs(previous_cross), abs(current_cross)) > zone.corridor_width_m / 2.0:
      return None
    crossing_fraction = -previous_along / (current_along - previous_along)
    crossing_cross = previous_cross + crossing_fraction * (current_cross - previous_cross)
    return crossing_fraction if abs(crossing_cross) <= zone.gate_arm_distance_m else None

  def _reload_if_changed(self) -> None:
    try:
      file_stat = os.stat(self.config_path)
      signature = (file_stat.st_mtime_ns, file_stat.st_ctime_ns, file_stat.st_size, file_stat.st_ino)
    except OSError:
      if self._observed_file_signature is not None:
        self._observed_file_signature = None
        self.apply_target = False
        self.zones = ()
        self.active_zone_ids.clear()
        self.active_zone_started_at.clear()
        self._update_target()
        log_event("personal_speed_zones_config_loaded", apply_target=False, zone_count=0)
      return
    if signature == self._observed_file_signature:
      return
    self._observed_file_signature = signature
    try:
      with open(self.config_path, encoding="utf-8") as config_file:
        apply_target, zones = self._parse_config(json.load(config_file))
    except (OSError, UnicodeError, json.JSONDecodeError, KeyError, TypeError, ValueError) as error:
      cloudlog.warning(f"Personal Speed Zones configuration ignored: {error}")
      return
    self.apply_target = apply_target
    self.zones = zones
    valid_ids = {zone.zone_id for zone in zones}
    self.active_zone_ids.intersection_update(valid_ids)
    self.active_zone_started_at = {zone_id: started_at for zone_id, started_at in self.active_zone_started_at.items() if zone_id in valid_ids}
    self._update_target()
    log_event("personal_speed_zones_config_loaded", apply_target=apply_target, zone_count=len(zones))

  def _update_target(self) -> None:
    self.target = min((zone.target for zone in self.zones if zone.zone_id in self.active_zone_ids), default=None)
    self.applied_target = min((zone.target for zone in self.zones if zone.zone_id in self.active_zone_ids and zone.apply_target), default=None)

  @staticmethod
  def _elapsed_seconds(previous_time, current_time) -> float:
    try:
      return float((current_time - previous_time).total_seconds())
    except (AttributeError, TypeError):
      return float(current_time) - float(previous_time)

  def _expire_active_zones(self, now) -> None:
    for zone_id, started_at in list(self.active_zone_started_at.items()):
      if self._elapsed_seconds(started_at, now) >= ACTIVE_ZONE_TIMEOUT_S:
        self.active_zone_ids.discard(zone_id)
        self.active_zone_started_at.pop(zone_id, None)
        log_event("personal_speed_zone_released", zone_id=zone_id, reason="timeout")

  def tick(self, now) -> None:
    """Reload configuration and expire zones without inventing a GPS sample."""
    self._reload_if_changed()
    self._expire_active_zones(now)
    self._update_target()

  def invalidate_position(self) -> None:
    """Break crossing continuity after GPS becomes stale or invalid."""
    self._previous_position = None
    self._previous_crossing_allowed = False
    self._previous_time = None
    self._last_sample_time = None

  def restore_active_zones(self, started_at_by_id, now) -> None:
    """Restore conservative on-road state after this process restarts."""
    if type(started_at_by_id) is not dict:
      return
    valid_ids = {zone.zone_id for zone in self.zones}
    for zone_id, started_at in started_at_by_id.items():
      if zone_id not in valid_ids or type(started_at) not in (int, float) or not math.isfinite(started_at):
        continue
      if 0 <= self._elapsed_seconds(started_at, now) < ACTIVE_ZONE_TIMEOUT_S:
        self.active_zone_ids.add(zone_id)
        self.active_zone_started_at[zone_id] = float(started_at)
    self._update_target()

  def update(self, gps_position: object, now) -> None:
    self.tick(now)
    current_position = self.parse_position(gps_position)
    if current_position is None:
      self.invalidate_position()
      return
    previous_position = self._previous_position
    plausible_movement = False
    if previous_position is not None:
      elapsed = self._elapsed_seconds(self._previous_time, now)
      sample_age = self._elapsed_seconds(self._last_sample_time, now)
      movement = distance(previous_position, current_position)
      max_movement = min(MAX_GPS_JUMP_M, MAX_GPS_SPEED_MPS * elapsed + GPS_ACCURACY_MARGIN_M)
      continuous = 0 < sample_age <= MAX_GPS_AGE_S
      plausible_movement = continuous and 0 < elapsed <= LOW_SPEED_ACCUMULATION_TIMEOUT_S and MIN_GPS_MOVEMENT_M <= movement <= max_movement
      if continuous and movement < MIN_GPS_MOVEMENT_M and 0 < elapsed < LOW_SPEED_ACCUMULATION_TIMEOUT_S:
        self._last_sample_time = now
        self._update_target()
        return
    if plausible_movement and self._previous_crossing_allowed:
      for zone in self.zones:
        events = []
        if zone.zone_id not in self.active_zone_ids:
          if (fraction := self._gate_crossing_fraction(previous_position, current_position, zone.start, zone)) is not None:
            events.append((fraction, "start"))
        if (fraction := self._gate_crossing_fraction(previous_position, current_position, zone.end, zone)) is not None:
          events.append((fraction, "end"))
        for _, event in sorted(events):
          if event == "start" and zone.zone_id not in self.active_zone_ids:
            self.active_zone_ids.add(zone.zone_id)
            self.active_zone_started_at[zone.zone_id] = now
            log_event("personal_speed_zone_activated", zone_id=zone.zone_id, target_mps=zone.target, apply_target=zone.apply_target)
          elif event == "end" and zone.zone_id in self.active_zone_ids:
            self.active_zone_ids.remove(zone.zone_id)
            self.active_zone_started_at.pop(zone.zone_id, None)
            log_event("personal_speed_zone_released", zone_id=zone.zone_id)
    self._previous_crossing_allowed = previous_position is None or plausible_movement
    self._previous_position = current_position
    self._previous_time = now
    self._last_sample_time = now
    self._update_target()
