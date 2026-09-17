"""Mapping between the zone controller and its fixed cereal service."""

import math


def active_cap(state):
  if not bool(state.restrictionActive):
    return None
  cap = state.effectiveCapMps
  return float(cap) if type(cap) in (int, float) and math.isfinite(cap) and cap >= 0 else None


def service_fields(controller, gps_fresh):
  enabled = any(zone.apply_target for zone in controller.zones)
  active = controller.applied_target is not None
  if active:
    source_state = "active" if gps_fresh else "active_gps_stale"
  elif not controller.zones:
    source_state = "no_zones"
  elif not enabled:
    source_state = "observation_only"
  elif not gps_fresh:
    source_state = "gps_unavailable"
  else:
    source_state = "ready"
  return {
    "enabled": enabled,
    "restrictionActive": active,
    "effectiveCapMps": controller.applied_target or 0.0,
    "hasTarget": controller.target is not None,
    "targetMps": controller.target or 0.0,
    "gpsFresh": gps_fresh,
    "sourceState": source_state,
    "zoneCount": min(len(controller.zones), 65535),
    "activeZoneCount": min(len(controller.active_zone_ids), 65535),
  }
