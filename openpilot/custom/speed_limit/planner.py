"""The one-way planner boundary for speed-limit restrictions."""
import math


def cap_cruise(driver_cruise_mps, state):
  """Return a lower-or-equal local cruise target from a typed state message.

  The flag is separate from the value because a default, stale, or unseen
  Cap'n Proto message contains zero scalar values. Once a road restriction is
  accepted, its retained cap still applies during source staleness; only an
  explicit release or a disabled setting clears `restrictionActive`.
  """
  if type(driver_cruise_mps) not in (int, float) or not math.isfinite(driver_cruise_mps) or driver_cruise_mps < 0:
    raise ValueError("driver cruise must be finite and nonnegative")
  if not bool(state.restrictionActive):
    return driver_cruise_mps
  cap = state.effectiveCapMps
  if type(cap) not in (int, float) or not math.isfinite(cap) or cap < 0:
    return driver_cruise_mps
  return min(driver_cruise_mps, cap)
