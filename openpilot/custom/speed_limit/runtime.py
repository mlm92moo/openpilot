"""Bridge a validated source state to the isolated speed-limit policy.

This module intentionally has no messaging or planner imports. A future process
will own I/O and publish this output through a typed service.
"""
from .controller import Config, Controller, SourceState


class Runtime:
  def __init__(self, controller=None):
    self.controller = Controller() if controller is None else controller
    self._signature = object()
    self._revision = 0

  def update(self, config, observer_status, driver_cruise_mps, action="none", accelerator_override_speed_mps=None,
             clear_manual_override=False):
    if not isinstance(config, Config) or not isinstance(observer_status, dict):
      raise ValueError("typed configuration and observer status required")
    required = {"rsa1_fresh", "persistent_primary_mps", "state"}
    if observer_status.keys() & required != required:
      raise ValueError("observer status is incomplete")
    value = observer_status["persistent_primary_mps"]
    fresh = observer_status["rsa1_fresh"] and value is not None
    signature = (value, observer_status["state"])
    if signature != self._signature:
      self._signature = signature
      self._revision += 1
    source = SourceState(self._revision, value, fresh, observer_status["state"])
    result = self.controller.update(config, source, driver_cruise_mps, action, accelerator_override_speed_mps,
                                    clear_manual_override)
    return {**result, "source_revision": self._revision,
            "detected_limit_mps": value if fresh else None,
            "detected_limit_fresh": fresh}
