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
  def test_whitelist_and_offroad_gate(self):
    params = FakeParams()
    with self.assertRaises(PermissionError):
      apply_settings(params, {"enabled": True}, False)
    with self.assertRaises(ValueError):
      apply_settings(params, {"arbitrary": 1}, True)

  def test_valid_update_and_clear_maximum(self):
    params = FakeParams()
    result = apply_settings(params, {"enabled": True, "offset_mps": 2.2352, "absolute_max_mps": 30.0,
                                     "auto_accept_lower": True, "auto_accept_higher": False}, True)
    self.assertTrue(result["enabled"])
    self.assertTrue(result["auto_accept_lower"])
    self.assertFalse(result["auto_accept_higher"])
    self.assertEqual(result["offset_mps"], 2.2352)
    self.assertEqual(result["absolute_max_mps"], 30.0)
    self.assertIsNone(apply_settings(params, {"absolute_max_mps": None}, True)["absolute_max_mps"])
