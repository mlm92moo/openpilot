"""Whitelisted settings for the local phone portal."""
import math

from openpilot.custom.speed_limit.controller import POSTED_SPEEDS_MPH


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


def _finite_number(value, name, low, high):
  if type(value) not in (int, float) or not math.isfinite(value) or not low <= value <= high:
    raise ValueError(f"{name} must be a finite number from {low} to {high}")
  return float(value)


def read_settings(params):
  absolute = params.get(SPEED_LIMIT_SETTINGS["absolute_max_mps"], return_default=True)
  personality = params.get(PERSONALITY_SETTINGS["driving_personality"], return_default=True)
  return {
    "enabled": params.get_bool(SPEED_LIMIT_SETTINGS["enabled"]),
    "source": "toyota_rsa",
    "auto_accept_lower": params.get_bool(SPEED_LIMIT_SETTINGS["auto_accept_lower"]),
    "auto_accept_higher": params.get_bool(SPEED_LIMIT_SETTINGS["auto_accept_higher"]),
    "absolute_max_mps": absolute if absolute is not None and absolute > 0 else None,
    "always_on_driver_monitoring": params.get_bool(BOOLEAN_SETTINGS["always_on_driver_monitoring"]),
    "lane_departure_warnings": params.get_bool(BOOLEAN_SETTINGS["lane_departure_warnings"]),
    "disengage_on_accelerator": params.get_bool(BOOLEAN_SETTINGS["disengage_on_accelerator"]),
    "local_phone_portal": params.get_bool(BOOLEAN_SETTINGS["local_phone_portal"]),
    "driving_personality": next((name for name, value in PERSONALITIES.items() if value == personality), "standard"),
    **{name: params.get(key, return_default=True) or 0.0 for name, key in SIGN_OFFSET_SETTINGS.items()},
  }


def apply_settings(params, payload, _is_offroad=None):
  if type(payload) is not dict or not payload or set(payload) - set(PORTAL_SETTINGS):
    raise ValueError("unknown or empty settings payload")
  for name, value in payload.items():
    key = PORTAL_SETTINGS[name]
    if name in BOOLEAN_SETTINGS or name in {"enabled", "auto_accept_lower", "auto_accept_higher"}:
      if type(value) is not bool:
        raise ValueError(f"{name} must be boolean")
      params.put_bool(key, value, block=True)
    elif name in SIGN_OFFSET_SETTINGS:
      params.put(key, _finite_number(value, name, -8.0, 12.0), block=True)
    elif name == "absolute_max_mps":
      if value is None:
        params.remove(key)
      else:
        params.put(key, _finite_number(value, name, 5.0, 55.0), block=True)
    elif name == "driving_personality":
      if value not in PERSONALITIES:
        raise ValueError("driving_personality must be aggressive, standard, or relaxed")
      params.put(key, PERSONALITIES[value], block=True)
  return read_settings(params)
