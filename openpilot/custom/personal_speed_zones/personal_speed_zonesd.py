"""Recognize directional saved zones and publish a cruise-cap candidate."""

import time

from openpilot.common.gps import get_gps_location_service
from openpilot.common.params import Params
from openpilot.common.realtime import Ratekeeper
import openpilot.cereal.messaging as messaging
from openpilot.custom.personal_speed_zones.controller import PersonalSpeedController
from openpilot.custom.personal_speed_zones.gps import GPSAdapter
from openpilot.custom.personal_speed_zones.persistence import restore_active_state, save_active_state
from openpilot.custom.personal_speed_zones.state import service_fields


def publish(pm, fields):
  message = messaging.new_message("personalSpeedZoneState", valid=True)
  for key, value in fields.items():
    setattr(message.personalSpeedZoneState, key, value)
  pm.send("personalSpeedZoneState", message)


def main():
  params = Params()
  gps_service = get_gps_location_service(params)
  gps_socket = messaging.sub_sock(gps_service, conflate=True)
  gps = GPSAdapter(gps_service)
  controller = PersonalSpeedController()
  publisher = messaging.PubMaster(["personalSpeedZoneState"])
  ratekeeper = Ratekeeper(10, print_delay_threshold=None)
  gps_was_fresh = False
  now = time.monotonic()
  controller.tick(now)
  restore_active_state(params, controller, now)
  previous_active_state = dict(controller.active_zone_started_at)

  while True:
    now = time.monotonic()
    message = messaging.recv_one_or_none(gps_socket)
    sample = gps.observe(message, now)
    if sample is not None:
      controller.update(sample.as_position(), now)
    else:
      controller.tick(now)
    gps_fresh = gps.current(now) is not None
    if gps_was_fresh and not gps_fresh:
      controller.invalidate_position()
    gps_was_fresh = gps_fresh
    if controller.active_zone_started_at != previous_active_state:
      save_active_state(params, controller)
      previous_active_state = dict(controller.active_zone_started_at)
    publish(publisher, service_fields(controller, gps_fresh))
    ratekeeper.keep_time()


if __name__ == "__main__":
  main()
