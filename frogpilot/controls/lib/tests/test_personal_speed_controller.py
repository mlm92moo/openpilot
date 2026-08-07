import datetime
import json
import math
import os

import pytest

from openpilot.common.conversions import Conversions as CV
from openpilot.frogpilot.controls.lib.personal_speed_controller import EARTH_RADIUS_M, PersonalSpeedController

BASE_LATITUDE = 37.0
BASE_LONGITUDE = -122.0


def position(north_m, east_m=0.0, bearing=0.0):
  latitude = BASE_LATITUDE + math.degrees(north_m / EARTH_RADIUS_M)
  longitude = BASE_LONGITUDE + math.degrees(east_m / (EARTH_RADIUS_M * math.cos(math.radians(BASE_LATITUDE))))
  return {"latitude": latitude, "longitude": longitude, "bearing": bearing}


def zone(zone_id="school-curve", target_mph=35, start_north_m=0, end_north_m=50, corridor_width_m=20):
  return {
    "id": zone_id,
    "enabled": True,
    "target_mph": target_mph,
    "start": position(start_north_m),
    "end": position(end_north_m),
    "corridor_width_m": corridor_width_m,
    "gate_arm_distance_m": 20,
    "heading_tolerance_deg": 20,
  }


def write_config(path, zones, apply_target=True):
  path.write_text(json.dumps({"apply_target": apply_target, "zones": zones}), encoding="utf-8")


@pytest.fixture
def configured_controller(tmp_path):
  config_path = tmp_path / "personal_speed_zones.json"
  write_config(config_path, [zone()])
  return PersonalSpeedController(str(config_path)), config_path


def update(controller, seconds, gps_position, enabled=True, openpilot_longitudinal=True):
  now = datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC) + datetime.timedelta(seconds=seconds)
  controller.update(gps_position, now, enabled, openpilot_longitudinal)


def activate(controller):
  update(controller, 0, position(-5))
  update(controller, 1, position(5))


def test_correct_direction_start_crossing_activates(configured_controller):
  controller, _ = configured_controller
  activate(controller)
  assert controller.active_zone_ids == {"school-curve"}
  assert controller.target == pytest.approx(35 * CV.MPH_TO_MS)


def test_wrong_direction_crossing_does_not_activate(configured_controller):
  controller, _ = configured_controller
  update(controller, 0, position(5, bearing=180))
  update(controller, 1, position(-5, bearing=180))
  assert not controller.active_zone_ids
  assert controller.target is None


def test_target_is_held_between_gates(configured_controller):
  controller, _ = configured_controller
  activate(controller)
  update(controller, 2, position(25))
  assert controller.get_target(30, True, True) == pytest.approx(35 * CV.MPH_TO_MS)


def test_end_gate_crossing_releases_target(configured_controller):
  controller, _ = configured_controller
  activate(controller)
  update(controller, 2, position(45))
  update(controller, 3, position(55))
  assert not controller.active_zone_ids
  assert controller.get_target(30, True, True) == 30


def test_overlapping_zones_use_lowest_target(tmp_path):
  config_path = tmp_path / "personal_speed_zones.json"
  write_config(config_path, [zone("fast-zone", 45), zone("slow-zone", 25)])
  controller = PersonalSpeedController(str(config_path))
  activate(controller)
  assert controller.active_zone_ids == {"fast-zone", "slow-zone"}
  assert controller.target == pytest.approx(25 * CV.MPH_TO_MS)


def test_malformed_reload_retains_last_valid_configuration(configured_controller):
  controller, config_path = configured_controller
  activate(controller)
  previous_mtime = config_path.stat().st_mtime_ns
  config_path.write_text("{not valid JSON", encoding="utf-8")
  os.utime(config_path, ns=(previous_mtime + 1_000_000_000, previous_mtime + 1_000_000_000))
  update(controller, 2, position(25))
  assert controller.active_zone_ids == {"school-curve"}
  assert controller.target == pytest.approx(35 * CV.MPH_TO_MS)


def test_temporary_gps_loss_retains_active_target(configured_controller):
  controller, _ = configured_controller
  activate(controller)
  update(controller, 2, None)
  assert controller.target == pytest.approx(35 * CV.MPH_TO_MS)
  assert controller.get_target(30, True, True) == pytest.approx(35 * CV.MPH_TO_MS)

  update(controller, 3, position(55))
  assert controller.active_zone_ids == {"school-curve"}


def test_parallel_road_is_rejected_by_cross_track_distance(tmp_path):
  config_path = tmp_path / "personal_speed_zones.json"
  write_config(config_path, [zone(corridor_width_m=10)])
  controller = PersonalSpeedController(str(config_path))
  update(controller, 0, position(-5, east_m=15))
  update(controller, 1, position(5, east_m=15))
  assert not controller.active_zone_ids


def test_implausible_gps_jump_does_not_activate(configured_controller):
  controller, _ = configured_controller
  update(controller, 0, position(-5))
  update(controller, 1, position(500))
  assert not controller.active_zone_ids


def test_stale_gps_breaks_crossing_continuity(configured_controller):
  controller, _ = configured_controller
  update(controller, 0, position(-5))
  update(controller, 0.5, position(-5))
  update(controller, 1.5, position(-5))
  update(controller, 2, position(5))
  assert not controller.active_zone_ids


def test_disengaged_crossing_does_not_activate(configured_controller):
  controller, _ = configured_controller
  update(controller, 0, position(-5), enabled=False)
  update(controller, 1, position(5), enabled=False)
  update(controller, 2, position(10), enabled=True)
  assert not controller.active_zone_ids


def test_driver_set_speed_below_zone_target_remains_controlling(configured_controller):
  controller, _ = configured_controller
  activate(controller)
  driver_target = 20 * CV.MPH_TO_MS
  assert controller.get_target(driver_target, True, True) == driver_target


def test_logging_only_mode_does_not_change_cruise_target(tmp_path):
  config_path = tmp_path / "personal_speed_zones.json"
  write_config(config_path, [zone()], apply_target=False)
  controller = PersonalSpeedController(str(config_path))
  activate(controller)
  assert controller.active_zone_ids == {"school-curve"}
  assert controller.get_target(30, True, True) == 30


def test_touchscreen_zone_can_apply_without_enabling_logging_only_zones(tmp_path):
  config_path = tmp_path / "personal_speed_zones.json"
  logging_zone = zone("logging-zone", 20)
  touchscreen_zone = zone("touchscreen-zone", 35)
  touchscreen_zone["apply_target"] = True
  write_config(config_path, [logging_zone, touchscreen_zone], apply_target=False)
  controller = PersonalSpeedController(str(config_path))
  activate(controller)
  assert controller.active_zone_ids == {"logging-zone", "touchscreen-zone"}
  assert controller.target == pytest.approx(20 * CV.MPH_TO_MS)
  assert controller.applied_target == pytest.approx(35 * CV.MPH_TO_MS)
  assert controller.get_target(30, True, True) == pytest.approx(35 * CV.MPH_TO_MS)


def test_pending_touchscreen_recording_is_not_loaded(tmp_path):
  config_path = tmp_path / "personal_speed_zones.json"
  pending_zone = zone()
  pending_zone["enabled"] = False
  pending_zone["pending_review"] = True
  write_config(config_path, [pending_zone], apply_target=True)
  controller = PersonalSpeedController(str(config_path))
  activate(controller)
  assert controller.zones == ()
  assert not controller.active_zone_ids
  assert controller.get_target(30, True, True) == 30


@pytest.mark.parametrize(("target_mph", "expected"), [(-1, 5.0), (200, 145 * CV.KPH_TO_MS)])
def test_configured_target_is_clamped(tmp_path, target_mph, expected):
  config_path = tmp_path / "personal_speed_zones.json"
  write_config(config_path, [zone(target_mph=target_mph)])
  controller = PersonalSpeedController(str(config_path))
  activate(controller)
  assert controller.target == pytest.approx(expected)
