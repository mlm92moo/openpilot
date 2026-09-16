#!/usr/bin/env python3
"""Publish passive Toyota RSA speed-limit state at 10 Hz.

This process reads local CAN and Params and publishes a typed status message.
It has no CAN transmit path and does not modify the planner. The controller is
disabled unless a future settings UI explicitly enables it.
"""
import time

from openpilot.common.constants import CV
from openpilot.common.params import Params
from openpilot.common.realtime import Ratekeeper
import openpilot.cereal.messaging as messaging

from openpilot.custom.rsa_observer.core import Config as ObserverConfig, Observer
from openpilot.custom.rsa_observer.inputs import cereal_event
from openpilot.custom.speed_limit import Config, Runtime
from openpilot.custom.speed_limit.controller import POSTED_SPEEDS_MPH
from openpilot.custom.speed_limit.state import service_fields


def _number(params, key, default=None):
  value = params.get(key, return_default=True)
  return default if value is None else value


def config_from_params(params):
  """Read only registered Params; invalid persisted values fail closed."""
  try:
    absolute = _number(params, "SpeedLimitAbsoluteMaxMps")
    if absolute is not None and absolute <= 0:
      absolute = None
    # Retain an older generic setting as the default only until each new
    # sign-specific setting has been saved through the portal.
    legacy_offset = _number(params, "SpeedLimitControlOffsetMps", 0.0)
    sign_offsets = tuple(_number(params, f"SpeedLimitControlOffset{mph}Mps", legacy_offset) for mph in POSTED_SPEEDS_MPH)
    return Config(
      enabled=params.get_bool("SpeedLimitControlEnabled"),
      auto_accept_lower=params.get_bool("SpeedLimitAutoAcceptLower"),
      auto_accept_higher=params.get_bool("SpeedLimitAutoAcceptHigher"),
      absolute_max_mps=absolute,
      sign_offsets_mps=sign_offsets,
    )
  except (TypeError, ValueError):
    return Config()


def publish(pm, fields, valid):
  message = messaging.new_message("speedLimitState")
  message.valid = valid
  for key, value in fields.items():
    setattr(message.speedLimitState, key, value)
  pm.send("speedLimitState", message)


def main():
  params = Params()
  observer = Observer(ObserverConfig())
  runtime = Runtime()
  can_sock = messaging.sub_sock("can", conflate=False)
  car_state_sock = messaging.sub_sock("carState", conflate=True)
  selfdrive_state_sock = messaging.sub_sock("selfdriveState", conflate=True)
  pm = messaging.PubMaster(["speedLimitState"])
  rk = Ratekeeper(10, print_delay_threshold=None)
  driver_cruise_mps = None
  accelerator_override_speed_mps = None
  brake_pressed = False
  openpilot_engaged = False

  while True:
    selfdrive_state = messaging.recv_one_or_none(selfdrive_state_sock)
    if selfdrive_state is not None and selfdrive_state.which() == "selfdriveState" and selfdrive_state.valid:
      openpilot_engaged = bool(selfdrive_state.selfdriveState.enabled)

    car_state = messaging.recv_one_or_none(car_state_sock)
    if car_state is not None and car_state.which() == "carState" and car_state.valid:
      driver_cruise_mps = car_state.carState.vCruise * CV.KPH_TO_MS
      v_ego = car_state.carState.vEgo
      brake_pressed = bool(car_state.carState.brakePressed)
      accelerator_override_speed_mps = v_ego if openpilot_engaged and car_state.carState.gasPressed and v_ego > 0 else None

    raw_can = messaging.drain_sock(can_sock)
    now_ns = time.monotonic_ns()
    can_valid = bool(raw_can) and all(message.which() == "can" and message.valid for message in raw_can)
    for message in raw_can:
      observer.observe(cereal_event(message), now_ns)
    status = observer.status(now_ns)

    # An unset cruise value is not a policy input. Publish source diagnostics
    # but do not advance controller state until carState supplies a positive value.
    if driver_cruise_mps is None or driver_cruise_mps <= 0:
      result = {"enabled": False, "restriction_active": False, "control_eligible": False, "source_state": "awaiting_driver_cruise",
                "source_revision": 0, "detected_limit_mps": None, "detected_limit_fresh": False,
                "accepted_limit_mps": None, "effective_cap_mps": 0.0}
    else:
      result = runtime.update(config_from_params(params), status, driver_cruise_mps,
                              accelerator_override_speed_mps=accelerator_override_speed_mps,
                              clear_manual_override=brake_pressed or not openpilot_engaged)
    publish(pm, service_fields(result), can_valid)
    rk.keep_time()


if __name__ == "__main__":
  main()
