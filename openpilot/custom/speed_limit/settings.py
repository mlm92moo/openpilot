"""Shared validation, migration, and serialized policy settings I/O.

All custom policy writers and readers take the same file lock. The eight legacy
scalar offset keys remain inspectable with Params; missing values migrate once
from the old generic offset. No controller reads a partly applied portal save.
"""
from contextlib import contextmanager
import hashlib
import json
import math
import os
import threading

from openpilot.custom.speed_limit.controller import Config, POSTED_SPEEDS_MPH

SPEED_LIMIT_SETTINGS = {
  "enabled": "SpeedLimitControlEnabled",
  "auto_accept_lower": "SpeedLimitAutoAcceptLower",
  "auto_accept_higher": "SpeedLimitAutoAcceptHigher",
  "absolute_max_mps": "SpeedLimitAbsoluteMaxMps",
}
SIGN_OFFSET_SETTINGS = {f"offset_{mph}_mps": f"SpeedLimitControlOffset{mph}Mps" for mph in POSTED_SPEEDS_MPH}
BOOLEAN_SETTINGS = {
  "always_on_driver_monitoring": "AlwaysOnDM",
  "lane_departure_warnings": "IsLdwEnabled",
  "disengage_on_accelerator": "DisengageOnAccelerator",
  "local_phone_portal": "SpeedLimitPortalEnabled",
}
PERSONALITY_SETTINGS = {"driving_personality": "LongitudinalPersonality"}
PORTAL_SETTINGS = SPEED_LIMIT_SETTINGS | SIGN_OFFSET_SETTINGS | BOOLEAN_SETTINGS | PERSONALITY_SETTINGS
PERSONALITIES = {"aggressive": 0, "standard": 1, "relaxed": 2}
_lock = threading.RLock()


class SettingsConflict(ValueError):
  pass


@contextmanager
def settings_lock(params):
  with _lock:
    # Production runs on Linux. Pure policy tests use an in-memory Params double.
    if hasattr(params, "get_param_path"):
      import fcntl
      with open(os.path.join(params.get_param_path(), ".speed_limit_settings.lock"), "a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
          yield
        finally:
          fcntl.flock(lock, fcntl.LOCK_UN)
    else:
      yield


def finite_number(value, name, low, high):
  if type(value) not in (int, float) or not math.isfinite(value) or not low <= value <= high:
    raise ValueError(f"{name} must be a finite number from {low} to {high}")
  return float(value)


def validate_payload(payload):
  if type(payload) is not dict or not payload or set(payload) - set(PORTAL_SETTINGS):
    raise ValueError("unknown or empty settings payload")
  result = {}
  for name, value in payload.items():
    if name in BOOLEAN_SETTINGS or name in {"enabled", "auto_accept_lower", "auto_accept_higher"}:
      if type(value) is not bool:
        raise ValueError(f"{name} must be boolean")
    elif name in SIGN_OFFSET_SETTINGS:
      value = finite_number(value, name, -8.0, 12.0)
    elif name == "absolute_max_mps" and value is not None:
      value = finite_number(value, name, 5.0, 55.0)
    elif name == "driving_personality":
      if type(value) is not str or value not in PERSONALITIES:
        raise ValueError("driving_personality must be aggressive, standard, or relaxed")
    result[name] = value
  return result


def _read_settings(params):
  offsets = {name: params.get(key) for name, key in SIGN_OFFSET_SETTINGS.items()}
  if any(value is None for value in offsets.values()):
    legacy = params.get("SpeedLimitControlOffsetMps")
    try:
      legacy = finite_number(0.0 if legacy is None else legacy, "legacy offset", -8.0, 12.0)
    except ValueError:
      legacy = 0.0
    for name, value in offsets.items():
      if value is None:
        params.put(SIGN_OFFSET_SETTINGS[name], legacy, block=True)
        offsets[name] = legacy
  for name, value in offsets.items():
    try:
      offsets[name] = finite_number(value, name, -8.0, 12.0)
    except ValueError:
      # A damaged persisted value cannot turn into a cap. Keep the raw value
      # until an explicit save replaces it, but use a safe zero in memory.
      offsets[name] = 0.0
  absolute = params.get(SPEED_LIMIT_SETTINGS["absolute_max_mps"])
  if absolute is not None:
    try:
      absolute = finite_number(absolute, "absolute_max_mps", 5.0, 55.0)
    except ValueError:
      absolute = None
  personality = params.get(PERSONALITY_SETTINGS["driving_personality"], return_default=True)
  result = {
    "enabled": params.get_bool(SPEED_LIMIT_SETTINGS["enabled"]),
    "auto_accept_lower": params.get_bool(SPEED_LIMIT_SETTINGS["auto_accept_lower"]),
    "auto_accept_higher": params.get_bool(SPEED_LIMIT_SETTINGS["auto_accept_higher"]),
    "absolute_max_mps": absolute,
    **{name: params.get_bool(key) for name, key in BOOLEAN_SETTINGS.items()},
    "driving_personality": next((name for name, value in PERSONALITIES.items() if value == personality), "standard"),
    **offsets,
  }
  return validate_payload(result)


def read_settings(params):
  with settings_lock(params):
    return _read_settings(params)


def settings_revision(settings):
  return hashlib.sha256(json.dumps(settings, sort_keys=True, allow_nan=False).encode()).hexdigest()


def config_from_params(params):
  values = read_settings(params)
  return Config(enabled=values["enabled"], auto_accept_lower=values["auto_accept_lower"],
                auto_accept_higher=values["auto_accept_higher"], absolute_max_mps=values["absolute_max_mps"],
                sign_offsets_mps=tuple(values[name] for name in SIGN_OFFSET_SETTINGS))


def apply_settings(params, payload, expected_revision=None):
  values = validate_payload(payload)  # No writes, including migration, before complete validation.
  with settings_lock(params):
    current = _read_settings(params)
    if expected_revision is not None and expected_revision != settings_revision(current):
      raise SettingsConflict("Settings changed elsewhere. Refresh, review your changes, and save again.")
    previous = {name: params.get(PORTAL_SETTINGS[name]) for name in values}
    try:
      for name, value in values.items():
        if name == "driving_personality":
          value = PERSONALITIES[value]
        key = PORTAL_SETTINGS[name]
        if value is None:
          params.remove(key)
        else:
          params.put(key, value, block=True)
    except Exception:
      for name, value in previous.items():
        key = PORTAL_SETTINGS[name]
        if value is None:
          params.remove(key)
        else:
          params.put(key, value, block=True)
      raise
    return _read_settings(params)
