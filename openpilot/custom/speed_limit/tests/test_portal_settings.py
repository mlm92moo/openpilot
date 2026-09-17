import unittest
from pathlib import Path

from openpilot.custom.speed_limit.portal_settings import SettingsConflict, apply_settings, read_settings, settings_revision


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
  def test_all_persisted_offset_keys_are_registered_as_floats(self):
    header = (Path(__file__).parents[3] / "common" / "params_keys.h").read_text()
    for mph in (20, 25, 30, 40, 50, 60, 70, 75):
      self.assertIn(f'{{"SpeedLimitControlOffset{mph}Mps", {{PERSISTENT, FLOAT}}}}', header)

  def test_whitelist_allows_onroad_update(self):
    params = FakeParams()
    with self.assertRaises(ValueError):
      apply_settings(params, {"arbitrary": 1})
    with self.assertRaises(ValueError):
      apply_settings(params, {"offset_mps": 1.0})
    self.assertTrue(apply_settings(params, {"enabled": True})["enabled"])

  def test_valid_update_and_clear_maximum(self):
    params = FakeParams()
    result = apply_settings(params, {"enabled": True, "offset_50_mps": 2.2352, "offset_60_mps": -1.0, "absolute_max_mps": 30.0,
                                     "auto_accept_lower": True, "auto_accept_higher": False})
    self.assertTrue(result["enabled"])
    self.assertTrue(result["auto_accept_lower"])
    self.assertFalse(result["auto_accept_higher"])
    self.assertEqual(result["offset_50_mps"], 2.2352)
    self.assertEqual(result["offset_60_mps"], -1.0)
    self.assertEqual(result["absolute_max_mps"], 30.0)
    self.assertIsNone(apply_settings(params, {"absolute_max_mps": None})["absolute_max_mps"])

  def test_invalid_save_is_all_or_nothing(self):
    params = FakeParams()
    apply_settings(params, {"enabled": False, "offset_20_mps": 1.0})
    before = dict(params.values)
    with self.assertRaises(ValueError):
      apply_settings(params, {"enabled": True, "offset_20_mps": 999.0})
    self.assertEqual(params.values, before)

  def test_old_generic_offset_migrates_once_and_is_visible_everywhere(self):
    params = FakeParams()
    params.put("SpeedLimitControlOffsetMps", 2.0)
    settings = read_settings(params)
    self.assertTrue(all(settings[f"offset_{mph}_mps"] == 2.0 for mph in (20, 25, 30, 40, 50, 60, 70, 75)))
    apply_settings(params, {"enabled": True})
    self.assertEqual(read_settings(params)["offset_50_mps"], 2.0)

  def test_stale_browser_revision_cannot_overwrite_newer_settings(self):
    params = FakeParams()
    revision = settings_revision(read_settings(params))
    apply_settings(params, {"offset_50_mps": 1.0})
    with self.assertRaises(SettingsConflict):
      apply_settings(params, {"offset_50_mps": 2.0}, revision)

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
