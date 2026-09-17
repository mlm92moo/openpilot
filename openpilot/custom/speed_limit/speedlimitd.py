#!/usr/bin/env python3
"""Publish Toyota RSA speed-limit state at 10 Hz.

This process reads local CAN and Params and publishes a typed status message.
It has no CAN transmit path. When enabled, the typed state is consumed by the
longitudinal planner as a one-way cruise cap.
"""
import time
import math

from openpilot.common.constants import CV
from openpilot.common.params import Params
from openpilot.common.realtime import Ratekeeper
import openpilot.cereal.messaging as messaging

from openpilot.custom.rsa_observer.core import Config as ObserverConfig, Observer
from openpilot.custom.rsa_observer.inputs import cereal_event
from openpilot.custom.speed_limit import Runtime
from openpilot.custom.speed_limit.settings import config_from_params
from openpilot.custom.speed_limit.state import service_fields
from openpilot.selfdrive.car.cruise import V_CRUISE_UNSET


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
  last_car_state_ns = None
  last_selfdrive_state_ns = None
  last_can_ns = None

  while True:
    selfdrive_state = messaging.recv_one_or_none(selfdrive_state_sock)
    if selfdrive_state is not None and selfdrive_state.which() == "selfdriveState" and selfdrive_state.valid:
      openpilot_engaged = bool(selfdrive_state.selfdriveState.enabled)
      last_selfdrive_state_ns = now_ns = time.monotonic_ns()

    car_state = messaging.recv_one_or_none(car_state_sock)
    if car_state is not None and car_state.which() == "carState" and car_state.valid:
      cruise_kph = car_state.carState.vCruise
      driver_cruise_mps = None if cruise_kph == V_CRUISE_UNSET or not math.isfinite(cruise_kph) else cruise_kph * CV.KPH_TO_MS
      v_ego = car_state.carState.vEgo
      brake_pressed = bool(car_state.carState.brakePressed)
      accelerator_override_speed_mps = v_ego if openpilot_engaged and car_state.carState.gasPressed and v_ego > 0 else None
      last_car_state_ns = time.monotonic_ns()

    raw_can = messaging.drain_sock(can_sock)
    now_ns = time.monotonic_ns()
    if raw_can and all(message.which() == "can" and message.valid for message in raw_can):
      last_can_ns = now_ns
    for message in raw_can:
      observer.observe(cereal_event(message), now_ns)
    status = observer.status(now_ns)

    inputs_healthy = (last_car_state_ns is not None and last_selfdrive_state_ns is not None
                      and now_ns - last_car_state_ns <= 1_000_000_000
                      and now_ns - last_selfdrive_state_ns <= 1_000_000_000)
    # An unset or stale cruise value is not a policy input. The invalid service
    # message makes the existing system health checks disengage rather than
    # silently dropping an already accepted speed cap.
    if not inputs_healthy or driver_cruise_mps is None or driver_cruise_mps <= 0:
      result = {"enabled": False, "restriction_active": False, "control_eligible": False, "source_state": "awaiting_driver_cruise",
                "source_revision": 0, "detected_limit_mps": None, "detected_limit_fresh": False,
                "accepted_limit_mps": None, "effective_cap_mps": 0.0}
    else:
      result = runtime.update(config_from_params(params), status, driver_cruise_mps,
                              accelerator_override_speed_mps=accelerator_override_speed_mps,
                              clear_manual_override=brake_pressed or not openpilot_engaged)
    can_healthy = last_can_ns is not None and now_ns - last_can_ns <= 1_000_000_000
    publish(pm, service_fields(result), inputs_healthy and can_healthy)
    rk.keep_time()


if __name__ == "__main__":
  main()
