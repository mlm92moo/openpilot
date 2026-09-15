"""Focused policy checks executable in a selected openpilot checkout."""
import math
import unittest

from openpilot.custom.speed_limit import Action, Config, Controller, Runtime, SourceState

MPH = .44704


def source(revision=1, mph=55, fresh=True, reason="numeric_observation"):
  return SourceState(revision, None if mph is None else mph * MPH, fresh, reason)


class ControllerTests(unittest.TestCase):
  def setUp(self):
    self.controller = Controller()
    self.driver = 75 * MPH

  def update(self, config, state, action=Action.NONE, driver=None):
    return self.controller.update(config, state, self.driver if driver is None else driver, action)

  def test_75_55_plus_5_then_70_retains_driver_cruise(self):
    config = Config(True, 5 * MPH, True, True)
    first = self.update(config, source(1, 55))
    self.assertAlmostEqual(first["effective_cap_mps"], 60 * MPH)
    later = self.update(config, source(2, 70))
    self.assertAlmostEqual(later["driver_cruise_mps"], 75 * MPH)
    self.assertAlmostEqual(later["effective_cap_mps"], 75 * MPH)

  def test_manual_acceptance_is_bound_to_current_revision(self):
    config = Config(True, 0, False, False)
    self.assertEqual(self.update(config, source(1, 55))["source_state"], "pending_acceptance")
    self.assertEqual(self.update(config, source(1, 55), Action.ACCEPT)["accepted_revision"], 1)
    result = self.update(config, source(2, 70))
    self.assertEqual(result["accepted_revision"], 1)
    self.assertEqual(result["pending_revision"], 2)

  def test_stale_restriction_needs_explicit_release(self):
    config = Config(True, 0, True, True)
    self.update(config, source(1, 55))
    stale = self.update(config, source(1, 55, False, "stale"))
    self.assertEqual(stale["source_state"], "stale_restriction")
    self.assertAlmostEqual(stale["effective_cap_mps"], 55 * MPH)
    released = self.update(config, source(1, 55, False, "stale"), Action.RELEASE)
    self.assertEqual(released["effective_cap_mps"], self.driver)

  def test_disabled_has_no_road_limit_and_absolute_cap_is_separate(self):
    disabled = self.update(Config(), source())
    self.assertEqual(disabled["effective_cap_mps"], self.driver)
    absolute = self.update(Config(False, absolute_max_mps=60 * MPH), source())
    self.assertAlmostEqual(absolute["effective_cap_mps"], 60 * MPH)

  def test_invalid_values_are_rejected(self):
    with self.assertRaises(ValueError):
      Config(offset_mps=math.nan)
    with self.assertRaises(ValueError):
      self.controller.update(Config(), source(), 0)

  def test_runtime_uses_only_persistent_fresh_observer_values(self):
    runtime = Runtime()
    config = Config(True, 5 * MPH, True, True)
    candidate = {"rsa1_fresh": True, "persistent_primary_mps": None, "state": "numeric_observation"}
    first = runtime.update(config, candidate, self.driver)
    self.assertEqual(first["source_state"], "unavailable")
    stable = {"rsa1_fresh": True, "persistent_primary_mps": 55 * MPH, "state": "numeric_observation"}
    accepted = runtime.update(config, stable, self.driver)
    self.assertAlmostEqual(accepted["effective_cap_mps"], 60 * MPH)
    revision = accepted["source_revision"]
    self.assertEqual(runtime.update(config, stable, self.driver)["source_revision"], revision)
    stale = runtime.update(config, {"rsa1_fresh": False, "persistent_primary_mps": 55 * MPH, "state": "stale"}, self.driver)
    self.assertEqual(stale["source_state"], "stale_restriction")
    self.assertAlmostEqual(stale["effective_cap_mps"], 60 * MPH)
