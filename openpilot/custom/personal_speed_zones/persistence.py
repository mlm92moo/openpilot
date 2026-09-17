"""Short-lived active-zone state used across daemon restarts."""

ACTIVE_STATE_PARAM = "PersonalSpeedZoneActiveState"


def restore_active_state(params, controller, now):
  value = params.get(ACTIVE_STATE_PARAM) or {}
  if not isinstance(value, dict):
    value = {}
  controller.restore_active_zones(value, now)


def save_active_state(params, controller):
  if controller.active_zone_started_at:
    params.put(ACTIVE_STATE_PARAM, controller.active_zone_started_at, block=False)
  else:
    params.remove(ACTIVE_STATE_PARAM)
