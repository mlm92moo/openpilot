# Personal Speed Zones

Personal Speed Zones are directional GPS-defined cruise caps for known turns. The controller was ported from the tested FrogPilot branch `personal-speed-zones-v2` at commit `05dda21db2e055ba745e25705be02ab5ff848986` and adapted to current stock openpilot services.

The feature stores zones in `/data/personal_speed_zones.json`. Each zone has a start gate, an end gate, travel bearing, target speed, corridor width, and heading tolerance. Crossing the start gate in the recorded direction activates the zone. Crossing the end gate releases it. Opposite-direction travel, adjacent roads, stale GPS, and implausible GPS jumps do not activate a zone. A missed end gate releases automatically after ten minutes.

The phone portal at port 8080 records and manages zones. **Mark slowdown** captures the comma's current GPS location and direction. **Mark resume** saves the end gate after at least 10 meters of travel. New zones can use a fixed 12–90 mph target or the lowest vehicle speed measured between the markers. An unfinished recording expires after 15 minutes. Re-recording nearly identical gates replaces the old portal-recorded zone.

The portal can edit the target, enable or disable individual zones, delete a zone, or erase all zones. Writes use atomic file replacement. Each modifying request includes the configuration revision it was based on, so an old browser page cannot overwrite a newer edit.

The `personal_speed_zonesd` process publishes `personalSpeedZoneState` independently from Toyota RSA. The longitudinal planner selects the lowest of the driver's cruise setting, the retained Toyota RSA cap, and the active Personal Speed Zone cap. Pressing the accelerator still provides the vehicle's normal temporary longitudinal override; releasing it restores the active saved-zone cap. Disengaging does not forget a recognized zone, so re-engaging before its exit restores that cap.

Active-zone timestamps are kept in a short-lived Params value so an unexpected `personal_speed_zonesd` restart does not forget a cap in the middle of a curve. The value clears when the manager starts or the car transitions offroad, and every restored zone still obeys the ten-minute timeout.

GPS comes from `gpsLocation` on comma 4 or `gpsLocationExternal` when an external receiver is configured. Samples require a valid fix, finite coordinates, heading accuracy of 90 degrees or better, and an age no greater than 1.5 seconds. External GPS samples also require reported horizontal accuracy of 50 meters or better. The current comma 4 `qcomgpsd` publisher does not populate horizontal accuracy, so its zero value is treated explicitly as unknown rather than as perfect accuracy. Losing GPS breaks gate-crossing continuity but does not suddenly release an already active cap.

The portal has no login and listens on the comma's local network interface, matching the existing local portal policy. Anyone on that network who can reach port 8080 can view or change its settings and saved zones.

The first road test should use one familiar route and a modest target reduction. Verify correct-direction activation, end-gate release, opposite-direction rejection, adjacent-road rejection, GPS-loss behavior, and interaction with Toyota RSA before recording additional zones.
