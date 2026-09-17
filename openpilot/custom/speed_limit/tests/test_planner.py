from types import SimpleNamespace
import unittest

from openpilot.custom.speed_limit.planner import cap_cruise, retained_cap


class PlannerBoundaryTests(unittest.TestCase):
  def test_default_or_inactive_state_is_identity(self):
    self.assertEqual(cap_cruise(30.0, SimpleNamespace(restrictionActive=False, effectiveCapMps=0.0)), 30.0)

  def test_applies_only_a_lower_active_cap(self):
    state = SimpleNamespace(restrictionActive=True, effectiveCapMps=25.0)
    self.assertEqual(cap_cruise(30.0, state), 25.0)
    self.assertEqual(cap_cruise(20.0, state), 20.0)

  def test_invalid_active_cap_fails_open_to_driver_cruise(self):
    state = SimpleNamespace(restrictionActive=True, effectiveCapMps=float("nan"))
    self.assertEqual(cap_cruise(30.0, state), 30.0)

  def test_invalid_or_missing_service_cannot_raise_an_accepted_cap(self):
    accepted = SimpleNamespace(enabled=True, restrictionActive=True, effectiveCapMps=25.0)
    self.assertEqual(retained_cap(None, accepted, True, True), 25.0)
    inactive_after_restart = SimpleNamespace(enabled=True, restrictionActive=False, effectiveCapMps=0.0)
    self.assertEqual(retained_cap(25.0, inactive_after_restart, True, True), 25.0)
    self.assertEqual(retained_cap(25.0, inactive_after_restart, False, False), 25.0)
    disabled = SimpleNamespace(enabled=False, restrictionActive=False, effectiveCapMps=0.0)
    self.assertIsNone(retained_cap(25.0, disabled, True, True))
