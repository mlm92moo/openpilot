"""The one-way planner boundary for speed-limit restrictions."""
import math


def active_cap(state):
  """Return a valid active cap, or None for an inactive/malformed message."""
  if not bool(state.restrictionActive):
    return None
  cap = state.effectiveCapMps
  if type(cap) not in (int, float) or not math.isfinite(cap) or cap < 0:
    return None
  return cap


def retained_cap(previous_cap, state, updated, valid):
  """Apply only healthy messages without silently raising an accepted cap.

  A valid enabled-but-inactive state can follow a speedlimitd restart. It does
  not release the prior accepted cap; the policy process normally publishes a
  retained active state for that case. A valid disabled state is the explicit
  user release path.
  """
  if type(updated) is not bool or type(valid) is not bool:
    raise ValueError("message health flags must be boolean")
  if not updated or not valid:
    return previous_cap
  cap = active_cap(state)
  if cap is not None:
    return cap
  return None if not bool(state.enabled) else previous_cap


def cap_cruise(driver_cruise_mps, state):
  """Return a lower-or-equal local cruise target from a typed state message.

  The flag is separate from the value because a default, stale, or unseen
  Cap'n Proto message contains zero scalar values. Once a road restriction is
  accepted, its retained cap still applies during source staleness; only an
  explicit release or a disabled setting clears `restrictionActive`.
  """
  if type(driver_cruise_mps) not in (int, float) or not math.isfinite(driver_cruise_mps) or driver_cruise_mps < 0:
    raise ValueError("driver cruise must be finite and nonnegative")
  cap = active_cap(state)
  if cap is None:
    return driver_cruise_mps
  return min(driver_cruise_mps, cap)
