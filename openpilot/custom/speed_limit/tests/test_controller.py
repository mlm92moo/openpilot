"""Focused policy checks executable in a selected openpilot checkout."""
import math
import unittest

from openpilot.custom.speed_limit import Action, Config, Controller, Runtime, SourceState
from openpilot.custom.speed_limit.controller import POSTED_SPEEDS_MPH

MPH = .44704


def source(revision=1, mph=55, fresh=True, reason="numeric_observation"):
  return SourceState(revision, None if mph is None else mph * MPH, fresh, reason)


def policy(enabled=True, lower=True, higher=True, absolute=None, offsets=None):
  values = [0.0] * len(POSTED_SPEEDS_MPH)
  for mph, offset in (offsets or {}).items():
    values[POSTED_SPEEDS_MPH.index(mph)] = offset * MPH
  return Config(enabled, lower, higher, absolute, tuple(values))


class ControllerTests(unittest.TestCase):
  def setUp(self):
    self.controller = Controller()
    self.driver = 75 * MPH

  def update(self, config, state, action=Action.NONE, driver=None):
    return self.controller.update(config, state, self.driver if driver is None else driver, action)

  def test_50_offset_does_not_apply_to_a_later_70_sign(self):
    config = policy(offsets={50: 5})
    first = self.update(config, source(1, 50))
    self.assertAlmostEqual(first["effective_cap_mps"], 55 * MPH)
    later = self.update(config, source(2, 70))
    self.assertAlmostEqual(later["driver_cruise_mps"], 75 * MPH)
    self.assertAlmostEqual(later["effective_cap_mps"], 70 * MPH)

  def test_manual_acceptance_is_bound_to_current_revision(self):
    config = policy(lower=False, higher=False)
    self.assertEqual(self.update(config, source(1, 55))["source_state"], "pending_acceptance")
    self.assertEqual(self.update(config, source(1, 55), Action.ACCEPT)["accepted_revision"], 1)
    result = self.update(config, source(2, 70))
    self.assertEqual(result["accepted_revision"], 1)
    self.assertEqual(result["pending_revision"], 2)

  def test_lower_only_does_not_accept_a_higher_first_candidate(self):
    config = policy(higher=False)
    higher = self.update(config, source(1, 80))
    self.assertEqual(higher["source_state"], "pending_acceptance")
    self.assertFalse(higher["restriction_active"])
    lower = self.update(config, source(2, 55))
    self.assertEqual(lower["source_state"], "accepted")
    self.assertAlmostEqual(lower["effective_cap_mps"], 55 * MPH)

  def test_stale_restriction_needs_explicit_release(self):
    config = policy()
    self.update(config, source(1, 55))
    stale = self.update(config, source(1, 55, False, "stale"))
    self.assertEqual(stale["source_state"], "stale_restriction")
    self.assertAlmostEqual(stale["effective_cap_mps"], 55 * MPH)
    released = self.update(config, source(1, 55, False, "stale"), Action.RELEASE)
    self.assertEqual(released["effective_cap_mps"], self.driver)

  def test_accelerator_override_holds_until_a_different_limit(self):
    config = policy()
    self.update(config, source(1, 55))
    override = self.controller.update(config, source(1, 55), self.driver, accelerator_override_speed_mps=68 * MPH)
    self.assertAlmostEqual(override["effective_cap_mps"], 68 * MPH)
    self.assertAlmostEqual(override["manual_override_cap_mps"], 68 * MPH)
    held = self.update(config, source(1, 55))
    self.assertAlmostEqual(held["effective_cap_mps"], 68 * MPH)
    changed = self.update(config, source(2, 60))
    self.assertIsNone(changed["manual_override_cap_mps"])
    self.assertAlmostEqual(changed["effective_cap_mps"], 60 * MPH)

  def test_accelerator_override_respects_driver_and_absolute_caps(self):
    config = policy(absolute=65 * MPH)
    self.update(config, source(1, 55))
    result = self.controller.update(config, source(1, 55), self.driver, accelerator_override_speed_mps=70 * MPH)
    self.assertAlmostEqual(result["manual_override_cap_mps"], 70 * MPH)
    self.assertAlmostEqual(result["effective_cap_mps"], 65 * MPH)

  def test_brake_or_disengagement_clears_only_accelerator_override(self):
    config = policy(offsets={50: 2})
    self.update(config, source(1, 50))
    self.controller.update(config, source(1, 50), self.driver, accelerator_override_speed_mps=68 * MPH)
    braked = self.controller.update(config, source(1, 50), self.driver, clear_manual_override=True)
    self.assertIsNone(braked["manual_override_cap_mps"])
    self.assertAlmostEqual(braked["effective_cap_mps"], 52 * MPH)
    self.controller.update(config, source(1, 50), self.driver, accelerator_override_speed_mps=66 * MPH)
    disengaged = self.controller.update(config, source(1, 50), self.driver, clear_manual_override=True)
    self.assertIsNone(disengaged["manual_override_cap_mps"])
    self.assertAlmostEqual(disengaged["effective_cap_mps"], 52 * MPH)

  def test_disabled_has_no_road_limit_and_absolute_cap_is_separate(self):
    disabled = self.update(Config(), source())
    self.assertEqual(disabled["effective_cap_mps"], self.driver)
    self.assertFalse(disabled["restriction_active"])
    absolute = self.update(Config(False, absolute_max_mps=60 * MPH), source())
    self.assertAlmostEqual(absolute["effective_cap_mps"], 60 * MPH)
    self.assertTrue(absolute["restriction_active"])

  def test_invalid_values_are_rejected(self):
    with self.assertRaises(ValueError):
      Config(sign_offsets_mps=(math.nan,) * len(POSTED_SPEEDS_MPH))
    with self.assertRaises(ValueError):
      self.controller.update(Config(), source(), 0)

  def test_acceptance_change_reconsiders_the_current_pending_sign(self):
    sign = source(1, 80)
    pending = self.update(policy(higher=False), sign)
    self.assertEqual(pending["source_state"], "pending_acceptance")
    accepted = self.update(policy(higher=True), sign)
    self.assertEqual(accepted["source_state"], "accepted")
    self.assertAlmostEqual(accepted["effective_cap_mps"], self.driver)

  def test_non_mph_sign_value_does_not_receive_an_nearby_offset(self):
    config = policy(offsets={25: 5})
    self.assertEqual(config.offset_for_limit_mps(40 / 3.6), 0.0)

  def test_runtime_uses_only_persistent_fresh_observer_values(self):
    runtime = Runtime()
    config = policy(offsets={50: 5})
    candidate = {"rsa1_fresh": True, "persistent_primary_mps": None, "state": "numeric_observation"}
    first = runtime.update(config, candidate, self.driver)
    self.assertEqual(first["source_state"], "unavailable")
    stable = {"rsa1_fresh": True, "persistent_primary_mps": 50 * MPH, "state": "numeric_observation"}
    accepted = runtime.update(config, stable, self.driver)
    self.assertAlmostEqual(accepted["effective_cap_mps"], 55 * MPH)
    revision = accepted["source_revision"]
    self.assertEqual(runtime.update(config, stable, self.driver)["source_revision"], revision)
    stale = runtime.update(config, {"rsa1_fresh": False, "persistent_primary_mps": 50 * MPH, "state": "stale"}, self.driver)
    self.assertEqual(stale["source_state"], "stale_restriction")
    self.assertAlmostEqual(stale["effective_cap_mps"], 55 * MPH)

  def test_only_a_matching_posted_speed_uses_its_offset(self):
    config = policy(offsets={50: 5, 60: -3})
    self.update(config, source(1, 50))
    self.assertAlmostEqual(self.update(config, source(1, 50))["effective_cap_mps"], 55 * MPH)
    self.assertAlmostEqual(self.update(config, source(2, 60))["effective_cap_mps"], 57 * MPH)
    self.assertAlmostEqual(self.update(config, source(3, 55))["effective_cap_mps"], 55 * MPH)
