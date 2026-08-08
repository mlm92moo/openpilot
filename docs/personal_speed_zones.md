# Personal Speed Zones

Personal Speed Zones are optional, directional GPS-defined cruise-speed targets for vehicles using openpilot longitudinal control. They do not send actuator commands, modify map data, or publish a posted speed limit. The selected target follows FrogPilot's normal `frogpilotPlan.vCruise` path into the longitudinal MPC.

Zones can be captured from the comma touchscreen; coordinates do not need to be entered while driving. The resulting configuration is stored in `/data/personal_speed_zones.json`. The controller watches the file's modification time, creation time, size, and inode so atomic replacements are reloaded reliably. A malformed update does not replace the last valid configuration; removing the file clears the loaded zones.

The controls are under **FrogPilot Settings → Gas / Brake → Mark Slowdown Button → MANAGE**. The main toggle shows or hides the recorder button without disabling saved zones. The management page also provides the target-speed selector, the lowest-recorded-speed option, and an **Erase All Saved Zones** action.

## Record a zone from the driving screen

When enabled, the recorder is available on the on-road screen whether openpilot is engaged or disengaged. It does not need to be armed while parked. **Marked Zone Speed** configures a fixed 12–90 mph target for newly recorded zones and defaults to 25 mph. Metric devices display the equivalent km/h while the file retains mph for compatibility. If **Use Lowest Recorded Speed** is enabled, the lowest valid vehicle speed observed between **MARK SLOWDOWN** and **MARK RESUME** is saved instead, rounded and limited to the same range.

One large button appears near the bottom center of the driving screen:

1. Tap **MARK SLOWDOWN** at the GPS point where deceleration should begin.
2. After passing through the turn, tap **MARK RESUME** where normal speed should resume.

Each tap snapshots GPS and speed when the button is pressed, then gives an audible confirmation and a brief on-screen status. The recorder rejects unavailable GPS, ignores rapid repeat taps, and requires the two points to be at least 10 meters apart. After saving the first point, hold **MARK RESUME** for 1.5 seconds to cancel that recording. An unfinished recording automatically cancels after 15 minutes; distance remains unlimited. After the second point is saved, the button resets to **MARK SLOWDOWN**, shows the number of zones currently loaded, and is immediately ready to record another zone. Re-recording nearly the same start, end, and direction updates the existing touchscreen zone rather than creating a duplicate. The recorder is hidden whenever an openpilot alert is displayed.

When a saved zone is recognized, a separate blue **ZONE ACTIVE** badge displays its target speed. This badge is independent of the recorder-button toggle, so saved-zone recognition remains visible when the recording button is hidden. If zones overlap, it displays the lowest active target.

New touchscreen-recorded zones have `enabled: true` and their own `apply_target: true`, so they work automatically on the next crossing. This per-zone override does not enable older logging-only zones. Manually configured zones continue to inherit the root `apply_target` setting unless they define their own override.

## Safe rollout

For manually configured zones, leave `apply_target` set to `false` for initial route validation. In this logging-only mode, the controller detects and retains zones but does not add its target to FrogPilot's candidate list. Touchscreen-recorded zones intentionally use a per-zone `apply_target: true` override and are active automatically. Route logs emit these events:

- `personal_speed_zone_activated`
- `personal_speed_zone_released`
- `personal_speed_zones_config_loaded`

Confirm correct-direction activation, wrong-direction rejection, adjacent-road rejection, end-gate release, and GPS-loss behavior before setting `apply_target` to `true`. Start active testing with a small target reduction in controlled conditions.

## Configuration

The root object contains:

- `apply_target`: `false` selects logging-only mode; `true` allows an active zone to constrain cruise speed.
- `zones`: a list of zone objects.

Each zone contains:

- `id`: a non-empty unique identifier.
- `enabled`: whether the zone is loaded.
- `apply_target`: optional per-zone override. If omitted, the zone inherits the root `apply_target` value.
- `target_mph`: the desired cap, converted to m/s and clamped to FrogPilot's effective 5 m/s through 145 km/h cruise-target range.
- `start` and `end`: objects containing `latitude`, `longitude`, and `bearing` in degrees. Bearing is clockwise from true north.
- `corridor_width_m`: maximum full corridor width. Both GPS samples used for a crossing must remain within half this width of the gate centerline.
- `gate_arm_distance_m`: maximum lateral distance from the gate center at the interpolated crossing point.
- `heading_tolerance_deg`: maximum difference between the GPS bearing and gate bearing.

## Gate and state behavior

A gate is a finite line perpendicular to its configured bearing. A crossing requires two consecutive, fresh, valid positions that move from the negative side to the positive side of the gate, match its heading, remain within the configured corridor, intersect its gate arm, and represent plausible vehicle movement. Being near a gate is not enough.

Crossing a start gate adds that zone to the recognized active set even while openpilot is disengaged or the gas pedal is overriding longitudinal control. Crossing its end gate removes it. The target affects cruise only while controls and openpilot longitudinal are active, so a gas-pedal crossing is remembered and the target becomes eligible after the pedal is released. Overlapping zones select the lowest target. A lower driver-set cruise target remains controlling because the final selection is `min(normal_target, personal_target)`.

Invalid or stale GPS breaks crossing continuity, so it cannot activate a new zone. Fresh crawl-speed samples may accumulate for up to five seconds to detect a gate crossing without accepting stale samples. If an end gate is missed, including because GPS was lost, the active zone automatically releases after 10 minutes.

Disengaging controls or openpilot longitudinal prevents the personal target from affecting cruise but does not prevent zone recognition. Re-engagement inside a recognized zone restores the cap until the end gate or 10-minute timeout releases it.

## Erasing saved zones

Choose **Erase All Saved Zones → ERASE** on the management page and confirm the warning. The configuration is atomically replaced with an empty zone list, and the controller drops any active saved-zone target when it reloads the file.

## Current limitations

- The on-device management page can erase all zones, but it does not yet list or edit individual zones.
- The local tangent-plane calculation is intended for short gate-crossing segments, not long-distance routing.
- The 10-minute active timeout means a single marked zone cannot continuously constrain cruise for longer than 10 minutes, even though its recorded distance is unlimited.
