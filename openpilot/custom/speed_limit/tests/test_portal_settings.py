import unittest

from openpilot.custom.speed_limit.portal_settings import apply_settings, read_settings


class FakeParams:
  def __init__(self):
    self.values = {}

  def get_bool(self, key):
    return self.values.get(key, False)

  def get(self, key, return_default=False):
    return self.values.get(key)

  def put_bool(self, key, value, block=False):
    self.values[key] = value

  def put(self, key, value, block=False):
    self.values[key] = value

  def remove(self, key):
    self.values.pop(key, None)


class PortalSettingsTests(unittest.TestCase):
  def test_whitelist_allows_onroad_update(self):
    params = FakeParams()
    with self.assertRaises(ValueError):
      apply_settings(params, {"arbitrary": 1}, True)
    with self.assertRaises(ValueError):
      apply_settings(params, {"offset_mps": 1.0}, True)
    self.assertTrue(apply_settings(params, {"enabled": True}, False)["enabled"])

  def test_valid_update_and_clear_maximum(self):
    params = FakeParams()
    result = apply_settings(params, {"enabled": True, "offset_50_mps": 2.2352, "offset_60_mps": -1.0, "absolute_max_mps": 30.0,
                                     "auto_accept_lower": True, "auto_accept_higher": False}, True)
    self.assertTrue(result["enabled"])
    self.assertTrue(result["auto_accept_lower"])
    self.assertFalse(result["auto_accept_higher"])
    self.assertEqual(result["offset_50_mps"], 2.2352)
    self.assertEqual(result["offset_60_mps"], -1.0)
    self.assertEqual(result["absolute_max_mps"], 30.0)
    self.assertIsNone(apply_settings(params, {"absolute_max_mps": None}, True)["absolute_max_mps"])

  def test_device_controls_are_whitelisted(self):
    params = FakeParams()
    result = apply_settings(params, {
      "always_on_driver_monitoring": True,
      "lane_departure_warnings": True,
      "disengage_on_accelerator": True,
      "local_phone_portal": True,
      "driving_personality": "relaxed",
    })
    self.assertTrue(result["always_on_driver_monitoring"])
    self.assertTrue(result["lane_departure_warnings"])
    self.assertTrue(result["disengage_on_accelerator"])
    self.assertTrue(result["local_phone_portal"])
    self.assertEqual(result["driving_personality"], "relaxed")
    with self.assertRaises(ValueError):
      apply_settings(params, {"driving_personality": "fast"})
