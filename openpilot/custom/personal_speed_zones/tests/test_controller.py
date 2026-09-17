import json
import math
import os
from pathlib import Path

import pytest

from openpilot.common.constants import CV
from openpilot.custom.personal_speed_zones.controller import ACTIVE_ZONE_TIMEOUT_S, EARTH_RADIUS_M, PersonalSpeedController

BASE_LATITUDE = 37.0
BASE_LONGITUDE = -122.0


def position(north_m, east_m=0.0, bearing=0.0):
  return {
    "latitude": BASE_LATITUDE + math.degrees(north_m / EARTH_RADIUS_M),
    "longitude": BASE_LONGITUDE + math.degrees(east_m / (EARTH_RADIUS_M * math.cos(math.radians(BASE_LATITUDE)))),
    "bearing": bearing,
  }


def zone(zone_id="curve", target_mph=35, end_north_m=50, corridor_width_m=20):
  return {
    "id": zone_id,
    "enabled": True,
    "target_mph": target_mph,
    "start": position(0),
    "end": position(end_north_m),
    "corridor_width_m": corridor_width_m,
    "gate_arm_distance_m": 20,
    "heading_tolerance_deg": 20,
  }


def controller(tmp_path: Path, zones=None, apply_target=True):
  path = tmp_path / "zones.json"
  path.write_text(json.dumps({"apply_target": apply_target, "zones": zones or [zone()]}))
  return PersonalSpeedController(str(path)), path


def update(instance, seconds, gps):
  instance.update(gps, seconds)


def activate(instance):
  update(instance, 0, position(-5))
  update(instance, 1, position(5))


def test_directional_crossing_activates_and_end_releases(tmp_path):
  instance, _ = controller(tmp_path)
  activate(instance)
  assert instance.applied_target == pytest.approx(35 * CV.MPH_TO_MS)
  update(instance, 2, position(45))
  update(instance, 3, position(55))
  assert instance.applied_target is None


def test_one_sample_crossing_both_gates_does_not_leave_short_zone_active(tmp_path):
  instance, _ = controller(tmp_path, [zone(end_north_m=15)])
  update(instance, 0, position(-5))
  update(instance, 1, position(25))
  assert not instance.active_zone_ids
  assert instance.applied_target is None


def test_wrong_direction_and_parallel_road_do_not_activate(tmp_path):
  instance, _ = controller(tmp_path, [zone(corridor_width_m=10)])
  update(instance, 0, position(5, bearing=180))
  update(instance, 1, position(-5, bearing=180))
  update(instance, 2, position(-5, east_m=15))
  update(instance, 3, position(5, east_m=15))
  assert not instance.active_zone_ids


def test_implausible_jump_and_stale_samples_break_crossing(tmp_path):
  instance, _ = controller(tmp_path)
  update(instance, 0, position(-5))
  update(instance, 1, position(500))
  assert not instance.active_zone_ids
  update(instance, 3, position(-5))
  update(instance, 4.6, position(5))
  assert not instance.active_zone_ids


def test_overlapping_zones_choose_lowest_applied_target(tmp_path):
  instance, _ = controller(tmp_path, [zone("fast", 45), zone("slow", 25)])
  activate(instance)
  assert instance.applied_target == pytest.approx(25 * CV.MPH_TO_MS)


def test_observation_only_zone_is_recognized_without_cap(tmp_path):
  instance, _ = controller(tmp_path, apply_target=False)
  activate(instance)
  assert instance.active_zone_ids == {"curve"}
  assert instance.target == pytest.approx(35 * CV.MPH_TO_MS)
  assert instance.applied_target is None


def test_per_zone_apply_override_preserves_logging_only_root(tmp_path):
  logging_zone = zone("logging", 20)
  applied_zone = zone("applied", 35)
  applied_zone["apply_target"] = True
  instance, _ = controller(tmp_path, [logging_zone, applied_zone], apply_target=False)
  activate(instance)
  assert instance.target == pytest.approx(20 * CV.MPH_TO_MS)
  assert instance.applied_target == pytest.approx(35 * CV.MPH_TO_MS)


def test_malformed_reload_retains_last_valid_configuration(tmp_path):
  instance, path = controller(tmp_path)
  activate(instance)
  path.write_text("{invalid")
  instance.tick(2)
  assert instance.active_zone_ids == {"curve"}
  assert instance.applied_target == pytest.approx(35 * CV.MPH_TO_MS)


def test_removing_or_disabling_active_zone_releases_it(tmp_path):
  instance, path = controller(tmp_path)
  activate(instance)
  path.write_text(json.dumps({"apply_target": True, "zones": []}))
  instance.tick(2)
  assert not instance.active_zone_ids
  assert instance.applied_target is None


def test_deleted_configuration_releases_active_zone(tmp_path):
  instance, path = controller(tmp_path)
  activate(instance)
  path.unlink()
  instance.tick(2)
  assert instance.zones == ()
  assert not instance.active_zone_ids
  assert instance.applied_target is None


def test_atomic_replacement_is_detected_when_mtime_is_unchanged(tmp_path):
  instance, path = controller(tmp_path)
  activate(instance)
  previous_mtime = path.stat().st_mtime_ns
  replacement = path.with_suffix(".new")
  replacement.write_text(json.dumps({"apply_target": False, "zones": []}))
  os.utime(replacement, ns=(previous_mtime, previous_mtime))
  os.replace(replacement, path)
  instance.tick(2)
  assert instance.zones == ()
  assert not instance.active_zone_ids


def test_gps_loss_retains_active_target_but_breaks_crossing_continuity(tmp_path):
  instance, _ = controller(tmp_path)
  activate(instance)
  instance.invalidate_position()
  assert instance.applied_target == pytest.approx(35 * CV.MPH_TO_MS)
  update(instance, 3, position(55))
  assert instance.active_zone_ids == {"curve"}


def test_active_zone_times_out_if_exit_is_missed(tmp_path):
  instance, _ = controller(tmp_path)
  activate(instance)
  instance.tick(ACTIVE_ZONE_TIMEOUT_S + 2)
  assert instance.applied_target is None


def test_active_zone_is_restored_after_process_restart(tmp_path):
  first, path = controller(tmp_path)
  activate(first)
  restarted = PersonalSpeedController(str(path))
  restarted.tick(2)
  restarted.restore_active_zones(first.active_zone_started_at, 2)
  assert restarted.active_zone_ids == {"curve"}
  assert restarted.applied_target == pytest.approx(35 * CV.MPH_TO_MS)
  restarted.tick(ACTIVE_ZONE_TIMEOUT_S + 2)
  assert restarted.applied_target is None


def test_crawl_speed_crossing_accumulates_small_movements(tmp_path):
  instance, _ = controller(tmp_path)
  for step in range(31):
    update(instance, step / 10, position(-0.6 + 0.04 * step))
  assert instance.active_zone_ids == {"curve"}


def test_crawl_speed_end_crossing_releases(tmp_path):
  instance, _ = controller(tmp_path)
  activate(instance)
  update(instance, 2, position(49.4))
  for step in range(1, 31):
    update(instance, 2 + step / 10, position(49.4 + 0.04 * step))
  assert not instance.active_zone_ids


@pytest.mark.parametrize(("target_mph", "expected"), [(-1, 5.0), (200, 145 * CV.KPH_TO_MS)])
def test_configured_target_is_clamped(tmp_path, target_mph, expected):
  instance, _ = controller(tmp_path, [zone(target_mph=target_mph)])
  activate(instance)
  assert instance.target == pytest.approx(expected)
