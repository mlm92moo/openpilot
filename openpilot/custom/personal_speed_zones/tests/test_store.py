from types import SimpleNamespace

import pytest

from openpilot.custom.personal_speed_zones import store
from openpilot.custom.personal_speed_zones.state import active_cap


def gate(latitude=37.0, longitude=-122.0, bearing=0.0):
  return {"latitude": latitude, "longitude": longitude, "bearing": bearing}


def test_record_save_edit_delete_and_stale_revision(tmp_path):
  path = tmp_path / "zones.json"
  config, revision = store.snapshot(path)
  assert config["zones"] == []
  zone = store.save_zone(gate(), gate(37.001), 25, path, revision)
  config, current_revision = store.snapshot(path)
  assert config["zones"][0]["id"] == zone["id"]
  with pytest.raises(store.ZoneConflict):
    store.update_zone(zone["id"], target_mph=30, path=path, expected_revision=revision)
  store.update_zone(zone["id"], target_mph=30, enabled=False, path=path, expected_revision=current_revision)
  config, current_revision = store.snapshot(path)
  assert config["zones"][0]["target_mph"] == 30
  assert config["zones"][0]["enabled"] is False
  store.delete_zone(zone["id"], path, current_revision)
  assert store.list_zones(path)["zones"] == []


def test_duplicate_recording_replaces_existing_zone(tmp_path):
  path = tmp_path / "zones.json"
  first = store.save_zone(gate(), gate(37.001), 25, path)
  second = store.save_zone(gate(37.00001), gate(37.00101), 30, path)
  config = store.list_zones(path)
  assert len(config["zones"]) == 1
  assert second["id"] == first["id"]
  assert config["zones"][0]["target_mph"] == 30


def test_recorder_uses_lowest_speed_and_times_out(tmp_path):
  recorder = store.Recorder()
  _, revision = store.snapshot(tmp_path / "zones.json")
  recorder.begin(gate(), 40, True, 20.0, 0.0, revision)
  recorder.observe_speed(15.0)
  zone = recorder.finish(gate(37.001), tmp_path / "zones.json")
  assert zone["target_mph"] == round(15.0 * 2.2369362920544)
  recorder.begin(gate(), 25, False, None, 0.0, store.snapshot(tmp_path / "zones.json")[1])
  assert recorder.expire(store.RECORDING_TIMEOUT_S)
  assert recorder.status(store.RECORDING_TIMEOUT_S)["recording"] is False


def test_zone_cap_is_independent_and_only_lowers_cruise():
  inactive = SimpleNamespace(restrictionActive=False, effectiveCapMps=0.0)
  active = SimpleNamespace(restrictionActive=True, effectiveCapMps=15.0)
  assert active_cap(inactive) is None
  assert min(20.0, active_cap(active)) == 15.0
  assert min(10.0, active_cap(active)) == 10.0
