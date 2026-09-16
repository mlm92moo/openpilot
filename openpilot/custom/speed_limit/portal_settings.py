"""Whitelisted settings for the local phone portal."""
import math


SPEED_LIMIT_SETTINGS = {
  "enabled": "SpeedLimitControlEnabled",
  "offset_mps": "SpeedLimitControlOffsetMps",
  "auto_accept_lower": "SpeedLimitAutoAcceptLower",
  "auto_accept_higher": "SpeedLimitAutoAcceptHigher",
  "absolute_max_mps": "SpeedLimitAbsoluteMaxMps",
}


def _finite_number(value, name, low, high):
  if type(value) not in (int, float) or not math.isfinite(value) or not low <= value <= high:
    raise ValueError(f"{name} must be a finite number from {low} to {high}")
  return float(value)


def read_settings(params):
  absolute = params.get(SPEED_LIMIT_SETTINGS["absolute_max_mps"], return_default=True)
  return {
    "enabled": params.get_bool(SPEED_LIMIT_SETTINGS["enabled"]),
    "source": "toyota_rsa",
    "offset_mps": params.get(SPEED_LIMIT_SETTINGS["offset_mps"], return_default=True) or 0.0,
    "auto_accept_lower": params.get_bool(SPEED_LIMIT_SETTINGS["auto_accept_lower"]),
    "auto_accept_higher": params.get_bool(SPEED_LIMIT_SETTINGS["auto_accept_higher"]),
    "absolute_max_mps": absolute if absolute is not None and absolute > 0 else None,
  }


def apply_settings(params, payload, _is_offroad=None):
  if type(payload) is not dict or not payload or set(payload) - set(SPEED_LIMIT_SETTINGS):
    raise ValueError("unknown or empty settings payload")
  for name, value in payload.items():
    key = SPEED_LIMIT_SETTINGS[name]
    if name in {"enabled", "auto_accept_lower", "auto_accept_higher"}:
      if type(value) is not bool:
        raise ValueError(f"{name} must be boolean")
      params.put_bool(key, value, block=True)
    elif name == "offset_mps":
      params.put(key, _finite_number(value, name, -8.0, 12.0), block=True)
    elif name == "absolute_max_mps":
      if value is None:
        params.remove(key)
      else:
        params.put(key, _finite_number(value, name, 5.0, 55.0), block=True)
  return read_settings(params)
