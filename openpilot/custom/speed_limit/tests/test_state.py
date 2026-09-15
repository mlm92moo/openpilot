import unittest

from openpilot.custom.speed_limit import Config, Runtime
from openpilot.custom.speed_limit.state import service_fields


class StateTests(unittest.TestCase):
  def test_optional_speeds_keep_explicit_presence_flags(self):
    fields = service_fields({
      "enabled": True, "restriction_active": True, "control_eligible": False, "source_state": "stale_restriction",
      "source_revision": 4, "detected_limit_mps": None, "detected_limit_fresh": False,
      "accepted_limit_mps": 24.5872, "effective_cap_mps": 24.5872,
    })
    self.assertFalse(fields["hasDetectedLimit"])
    self.assertEqual(fields["detectedLimitMps"], 0.0)
    self.assertTrue(fields["hasAcceptedLimit"])
    self.assertTrue(fields["restrictionActive"])
    self.assertEqual(fields["sourceState"], "stale_restriction")

  def test_malformed_policy_output_is_rejected(self):
    with self.assertRaises(ValueError):
      service_fields({"enabled": True})

  def test_runtime_output_maps_to_active_restriction(self):
    result = Runtime().update(Config(True, 0, True, True), {
      "rsa1_fresh": True, "persistent_primary_mps": 25.0, "state": "numeric_observation",
    }, 30.0)
    fields = service_fields(result)
    self.assertTrue(fields["enabled"])
    self.assertTrue(fields["restrictionActive"])
    self.assertEqual(fields["effectiveCapMps"], 25.0)
