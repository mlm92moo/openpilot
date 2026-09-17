from types import SimpleNamespace

from openpilot.custom.personal_speed_zones.persistence import ACTIVE_STATE_PARAM, restore_active_state, save_active_state


class FakeParams:
  def __init__(self, value=None):
    self.value = value
    self.puts = []
    self.removes = []

  def get(self, key):
    assert key == ACTIVE_STATE_PARAM
    return self.value

  def put(self, key, value, block=False):
    self.puts.append((key, value, block))

  def remove(self, key):
    self.removes.append(key)


def test_restore_passes_typed_json_object_to_controller():
  params = FakeParams({"curve": 12.0})
  controller = SimpleNamespace(restore_active_zones=lambda value, now: setattr(controller, "restored", (value, now)))
  restore_active_state(params, controller, 15.0)
  assert controller.restored == ({"curve": 12.0}, 15.0)


def test_restore_rejects_non_object_json_value():
  params = FakeParams(["curve"])
  controller = SimpleNamespace(restore_active_zones=lambda value, now: setattr(controller, "restored", (value, now)))
  restore_active_state(params, controller, 15.0)
  assert controller.restored == ({}, 15.0)


def test_save_uses_params_json_type_and_removes_empty_state():
  params = FakeParams()
  controller = SimpleNamespace(active_zone_started_at={"curve": 12.0})
  save_active_state(params, controller)
  assert params.puts == [(ACTIVE_STATE_PARAM, {"curve": 12.0}, False)]

  controller.active_zone_started_at = {}
  save_active_state(params, controller)
  assert params.removes == [ACTIVE_STATE_PARAM]
