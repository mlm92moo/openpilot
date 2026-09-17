"""Atomic JSON storage and recording rules for Personal Speed Zones."""

import copy
import hashlib
import json
import math
import os
import tempfile
import threading
import time

from openpilot.common.constants import CV
from openpilot.custom.personal_speed_zones.controller import CONFIG_PATH, GPSPosition, angular_difference, distance

MIN_ZONE_LENGTH_M = 10.0
DUPLICATE_DISTANCE_M = 12.0
DUPLICATE_BEARING_DEG = 20.0
RECORDING_TIMEOUT_S = 15 * 60
_lock = threading.RLock()


class ZoneConflict(ValueError):
  pass


def _default_config():
  return {"apply_target": False, "zones": []}


def _finite(value, name, low, high):
  if type(value) not in (int, float) or not math.isfinite(value) or not low <= value <= high:
    raise ValueError(f"{name} must be from {low} to {high}")
  return float(value)


def validate_gate(value, name="gate"):
  if type(value) is not dict:
    raise ValueError(f"{name} is unavailable")
  return {
    "latitude": _finite(value.get("latitude"), f"{name} latitude", -90, 90),
    "longitude": _finite(value.get("longitude"), f"{name} longitude", -180, 180),
    "bearing": _finite(value.get("bearing"), f"{name} bearing", 0, 360) % 360.0,
  }


def _read(path=CONFIG_PATH):
  try:
    with open(path, encoding="utf-8") as config_file:
      config = json.load(config_file)
  except FileNotFoundError:
    return _default_config()
  except (OSError, UnicodeError, json.JSONDecodeError) as exc:
    raise ValueError(f"saved zones cannot be read: {exc}") from exc
  if type(config) is not dict or type(config.get("zones")) is not list or type(config.get("apply_target", False)) is not bool:
    raise ValueError("saved zones have an invalid format")
  if any(type(zone) is not dict or type(zone.get("id")) is not str or not zone["id"].strip() for zone in config["zones"]):
    raise ValueError("each saved zone must be an object with an ID")
  config.setdefault("apply_target", False)
  return config


def _write(config, path=CONFIG_PATH):
  directory = os.path.dirname(path) or "."
  os.makedirs(directory, exist_ok=True)
  descriptor, temporary = tempfile.mkstemp(prefix=".personal_speed_zones.", dir=directory)
  try:
    with os.fdopen(descriptor, "w", encoding="utf-8") as output:
      json.dump(config, output, allow_nan=False, indent=2, sort_keys=True)
      output.write("\n")
      output.flush()
      os.fsync(output.fileno())
    os.replace(temporary, path)
  finally:
    try:
      os.unlink(temporary)
    except FileNotFoundError:
      pass


def list_zones(path=CONFIG_PATH):
  with _lock:
    return copy.deepcopy(_read(path))


def revision(config):
  return hashlib.sha256(json.dumps(config, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def snapshot(path=CONFIG_PATH):
  config = list_zones(path)
  return config, revision(config)


def _raw_revision(path):
  try:
    with open(path, "rb") as config_file:
      contents = config_file.read()
  except OSError as exc:
    raise ValueError(f"saved zones cannot be read: {exc}") from exc
  return "invalid:" + hashlib.sha256(contents).hexdigest()


def snapshot_for_portal(path=CONFIG_PATH):
  """Keep the portal usable when the saved-zone file needs recovery."""
  with _lock:
    try:
      config = _read(path)
      return copy.deepcopy(config), revision(config), None
    except ValueError as exc:
      return _default_config(), _raw_revision(path), str(exc)


def _check_revision(config, expected_revision):
  if expected_revision is not None and revision(config) != expected_revision:
    raise ZoneConflict("Saved zones changed elsewhere. Refresh and try again.")


def _point(gate):
  return GPSPosition(gate["latitude"], gate["longitude"], gate["bearing"])


def _duplicate(zone, start, end):
  if not zone.get("recorded_from_portal", zone.get("recorded_from_ui", False)):
    return False
  try:
    existing_start, existing_end = validate_gate(zone["start"]), validate_gate(zone["end"])
  except (KeyError, ValueError):
    return False
  return (
    distance(_point(existing_start), _point(start)) <= DUPLICATE_DISTANCE_M
    and distance(_point(existing_end), _point(end)) <= DUPLICATE_DISTANCE_M
    and angular_difference(existing_start["bearing"], start["bearing"]) <= DUPLICATE_BEARING_DEG
    and angular_difference(existing_end["bearing"], end["bearing"]) <= DUPLICATE_BEARING_DEG
  )


def save_zone(start, end, target_mph, path=CONFIG_PATH, expected_revision=None):
  start, end = validate_gate(start, "start"), validate_gate(end, "end")
  target_mph = _finite(target_mph, "target speed", 12, 90)
  if distance(_point(start), _point(end)) < MIN_ZONE_LENGTH_M:
    raise ValueError("drive at least 10 meters before marking resume")
  with _lock:
    config = _read(path)
    _check_revision(config, expected_revision)
    zone_id = "recorded-" + time.strftime("%Y%m%d-%H%M%S", time.gmtime())
    zone = {
      "id": zone_id,
      "enabled": True,
      "apply_target": True,
      "recorded_from_portal": True,
      "target_mph": target_mph,
      "start": start,
      "end": end,
      "corridor_width_m": 20.0,
      "gate_arm_distance_m": 20.0,
      "heading_tolerance_deg": 25.0,
    }
    for index, existing in enumerate(config["zones"]):
      if type(existing) is dict and _duplicate(existing, start, end):
        zone["id"] = existing.get("id", zone_id)
        config["zones"][index] = zone
        break
    else:
      used_ids = {item.get("id") for item in config["zones"] if type(item) is dict}
      suffix = 2
      while zone["id"] in used_ids:
        zone["id"] = f"{zone_id}-{suffix}"
        suffix += 1
      config["zones"].append(zone)
    _write(config, path)
    return copy.deepcopy(zone)


def update_zone(zone_id, *, enabled=None, target_mph=None, path=CONFIG_PATH, expected_revision=None):
  with _lock:
    config = _read(path)
    _check_revision(config, expected_revision)
    match = next((zone for zone in config["zones"] if type(zone) is dict and zone.get("id") == zone_id), None)
    if match is None:
      raise ValueError("saved zone was not found")
    if enabled is not None:
      if type(enabled) is not bool:
        raise ValueError("enabled must be boolean")
      match["enabled"] = enabled
    if target_mph is not None:
      match["target_mph"] = _finite(target_mph, "target speed", 12, 90)
    _write(config, path)
    return copy.deepcopy(match)


def delete_zone(zone_id, path=CONFIG_PATH, expected_revision=None):
  with _lock:
    config = _read(path)
    _check_revision(config, expected_revision)
    remaining = [zone for zone in config["zones"] if not (type(zone) is dict and zone.get("id") == zone_id)]
    if len(remaining) == len(config["zones"]):
      raise ValueError("saved zone was not found")
    config["zones"] = remaining
    _write(config, path)


def clear_zones(path=CONFIG_PATH, expected_revision=None):
  with _lock:
    try:
      current_revision = revision(_read(path))
    except ValueError:
      current_revision = _raw_revision(path)
    if expected_revision is not None and current_revision != expected_revision:
      raise ZoneConflict("Saved zones changed elsewhere. Refresh and try again.")
    _write(_default_config(), path)


class Recorder:
  def __init__(self):
    self.start = None
    self.started_at = None
    self.target_mph = None
    self.use_lowest_speed = False
    self.lowest_speed_mps = None
    self.config_revision = None

  def expire(self, now):
    if self.started_at is not None and now - self.started_at >= RECORDING_TIMEOUT_S:
      self.cancel()
      return True
    return False

  def begin(self, position, target_mph, use_lowest_speed, speed_mps, now, config_revision):
    start = validate_gate(position, "start")
    target_mph = _finite(target_mph, "target speed", 12, 90)
    if type(use_lowest_speed) is not bool:
      raise ValueError("use_lowest_speed must be boolean")
    lowest_speed_mps = _finite(speed_mps, "vehicle speed", 0, 100) if use_lowest_speed else None
    self.start = start
    self.target_mph = target_mph
    self.use_lowest_speed = use_lowest_speed
    self.lowest_speed_mps = lowest_speed_mps
    self.started_at = now
    self.config_revision = config_revision

  def observe_speed(self, speed_mps):
    if self.started_at is not None and self.use_lowest_speed and self.lowest_speed_mps is not None and math.isfinite(speed_mps) and speed_mps >= 0:
      self.lowest_speed_mps = min(self.lowest_speed_mps, speed_mps)

  def finish(self, position, path=CONFIG_PATH):
    if self.start is None:
      raise ValueError("mark slowdown first")
    target = round(self.lowest_speed_mps * CV.MS_TO_MPH) if self.use_lowest_speed else self.target_mph
    target = min(max(target, 12), 90)
    zone = save_zone(self.start, position, target, path, self.config_revision)
    self.cancel()
    return zone

  def cancel(self):
    self.__init__()

  def status(self, now):
    self.expire(now)
    return {
      "recording": self.start is not None,
      "target_mph": self.target_mph,
      "use_lowest_speed": self.use_lowest_speed,
      "elapsed_s": None if self.started_at is None else now - self.started_at,
    }
