"""Deterministic policy for an external speed-limit source.

The caller owns CAN decoding, persistence, settings I/O, UI and messaging. This
module deliberately has no openpilot imports and cannot change a vehicle on its
own. It returns an effective planner cap while retaining the driver's cruise
value as a separate input.
"""
from dataclasses import dataclass
from enum import StrEnum
import math


class Action(StrEnum):
  NONE = "none"
  ACCEPT = "accept"
  RELEASE = "release"


def finite_positive(name, value):
  if type(value) not in (int, float) or not math.isfinite(value) or value <= 0:
    raise ValueError(f"{name} must be a finite positive number")
  return float(value)


@dataclass(frozen=True)
class Config:
  """Already validated immutable configuration read outside the planner loop."""
  enabled: bool = False
  offset_mps: float = 0.0
  auto_accept_lower: bool = False
  auto_accept_higher: bool = False
  absolute_max_mps: float | None = None

  def __post_init__(self):
    if type(self.enabled) is not bool or type(self.auto_accept_lower) is not bool or type(self.auto_accept_higher) is not bool:
      raise ValueError("boolean configuration expected")
    if type(self.offset_mps) not in (int, float) or not math.isfinite(self.offset_mps):
      raise ValueError("offset_mps must be finite")
    if self.absolute_max_mps is not None:
      finite_positive("absolute_max_mps", self.absolute_max_mps)


@dataclass(frozen=True)
class SourceState:
  """A source adapter's current validated candidate, never raw CAN data."""
  revision: int
  limit_mps: float | None
  fresh: bool
  reason: str

  def __post_init__(self):
    if type(self.revision) is not int or self.revision < 0:
      raise ValueError("revision must be a nonnegative integer")
    if type(self.fresh) is not bool or not isinstance(self.reason, str) or not self.reason:
      raise ValueError("invalid source status")
    if self.limit_mps is not None:
      finite_positive("limit_mps", self.limit_mps)


class Controller:
  """Acceptance, retention and cap composition for one source.

  Runtime state stays in memory. A process restart starts with no accepted road
  limit. A stale accepted restriction is held and labelled until explicit
  release or a fresh accepted successor prevents a surprise acceleration.
  """
  def __init__(self):
    self.accepted_revision = None
    self.accepted_limit_mps = None
    self.pending_revision = None
    self.pending_limit_mps = None
    self.last_source_revision = None

  def clear_road_limit(self):
    self.accepted_revision = None
    self.accepted_limit_mps = None
    self.pending_revision = None
    self.pending_limit_mps = None

  def _accept(self, source):
    self.accepted_revision = source.revision
    self.accepted_limit_mps = float(source.limit_mps)
    self.pending_revision = None
    self.pending_limit_mps = None

  def _consider_source(self, config, source, action):
    if source.limit_mps is None or not source.fresh:
      # A source disappearing does not implicitly release a previously accepted
      # restriction. A new numeric candidate must be fresh to be considered.
      return
    is_new = source.revision != self.last_source_revision
    if not is_new and action != Action.ACCEPT:
      return
    self.last_source_revision = source.revision
    if action == Action.ACCEPT:
      self._accept(source)
      return
    if self.accepted_limit_mps is None:
      automatic = config.auto_accept_lower or config.auto_accept_higher
    elif source.limit_mps < self.accepted_limit_mps:
      automatic = config.auto_accept_lower
    elif source.limit_mps > self.accepted_limit_mps:
      automatic = config.auto_accept_higher
    else:
      automatic = True
    if automatic:
      self._accept(source)
    else:
      self.pending_revision = source.revision
      self.pending_limit_mps = float(source.limit_mps)

  def update(self, config, source, driver_cruise_mps, action=Action.NONE):
    """Return serializable policy state for exactly one planner cycle.

    `driver_cruise_mps` is never stored or modified. A caller with stock cruise
    sentinels must bypass this method until it has a valid positive m/s value.
    """
    if not isinstance(config, Config) or not isinstance(source, SourceState):
      raise ValueError("typed configuration and source required")
    finite_positive("driver_cruise_mps", driver_cruise_mps)
    try:
      action = Action(action)
    except ValueError as exc:
      raise ValueError("unknown action") from exc

    if action == Action.RELEASE:
      self.clear_road_limit()
      self.last_source_revision = source.revision
    if config.enabled:
      self._consider_source(config, source, action)
    else:
      # Turning the source feature off removes all road-limit runtime state.
      self.clear_road_limit()
      # Re-enabling must consider the current fresh candidate even when its
      # source revision did not change while the feature was disabled.
      self.last_source_revision = None

    caps = [float(driver_cruise_mps)]
    if config.absolute_max_mps is not None:
      caps.append(float(config.absolute_max_mps))
    source_state = "disabled" if not config.enabled else "unavailable"
    road_cap = None
    if config.enabled and self.accepted_limit_mps is not None:
      # The source may be stale, but the retained cap is visibly distinct.
      road_cap = finite_positive("accepted offset cap", self.accepted_limit_mps + config.offset_mps)
      caps.append(road_cap)
      source_state = "accepted" if source.fresh and source.limit_mps is not None else "stale_restriction"
    elif config.enabled and self.pending_limit_mps is not None:
      source_state = "pending_acceptance" if source.fresh else "stale_pending"
    elif config.enabled and source.limit_mps is not None:
      source_state = "candidate" if source.fresh else "stale"

    effective = min(caps)
    return {
      "enabled": config.enabled,
      "restriction_active": bool(config.absolute_max_mps is not None or (config.enabled and self.accepted_limit_mps is not None)),
      "driver_cruise_mps": float(driver_cruise_mps),
      "effective_cap_mps": effective,
      "road_cap_mps": road_cap,
      "absolute_cap_mps": config.absolute_max_mps,
      "source_state": source_state,
      "source_reason": source.reason,
      "source_fresh": source.fresh,
      "accepted_limit_mps": self.accepted_limit_mps,
      "accepted_revision": self.accepted_revision,
      "pending_limit_mps": self.pending_limit_mps,
      "pending_revision": self.pending_revision,
      "control_eligible": config.enabled and self.accepted_limit_mps is not None and source.fresh,
    }
