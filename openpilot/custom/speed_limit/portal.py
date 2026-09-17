#!/usr/bin/env python3
"""Local-network phone portal for speed-limit settings."""

from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import threading
import time

from openpilot.common.params import Params
import openpilot.cereal.messaging as messaging

from openpilot.custom.personal_speed_zones.gps import GPSAdapter
from openpilot.custom.personal_speed_zones import store as zone_store
from openpilot.custom.speed_limit.settings import SettingsConflict, apply_settings, read_settings, settings_revision

PORT = 8080
ENABLED_PARAM = "SpeedLimitPortalEnabled"


class LocalPortalServer(ThreadingHTTPServer):
  daemon_threads = True
  request_queue_size = 8


PAGE = """<!doctype html>
<html lang=en><meta name=viewport content="width=device-width,initial-scale=1">
<title>comma control</title>
<style>
:root{color-scheme:dark;--bg:#0a1020;--card:#141e35;--line:#2a3856;--text:#f5f7ff;--muted:#9eacc7;--accent:#69e4b0;--danger:#ff9a9a}
*{box-sizing:border-box}body{margin:0;background:radial-gradient(circle at 15% 0,#1d315a 0,transparent 28rem),var(--bg);color:var(--text);font:16px system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}
.app{max-width:42rem;margin:auto;padding:1.15rem 1rem 3rem}.hero{display:flex;justify-content:space-between;gap:1rem;align-items:start;margin:.25rem 0 1.2rem}.eyebrow{margin:0;color:var(--accent);font-size:.75rem;font-weight:800;letter-spacing:.13em;text-transform:uppercase}.hero h1{font-size:2rem;margin:.2rem 0}.subtle{color:var(--muted);margin:0}.connection{border:1px solid var(--line);border-radius:999px;padding:.4rem .65rem;font-size:.82rem;white-space:nowrap}.dot{display:inline-block;width:.55rem;height:.55rem;border-radius:50%;background:#ffb0b0;margin-right:.35rem}.dot.ok{background:var(--accent);box-shadow:0 0 .7rem var(--accent)}
.card{background:linear-gradient(145deg,#192641,var(--card));border:1px solid var(--line);border-radius:1rem;padding:1rem;margin:.85rem 0;box-shadow:0 1rem 3rem #0003}.card h2{font-size:1.05rem;margin:0 0 .2rem}.card p{color:var(--muted);font-size:.9rem;margin:.2rem 0 1rem}.stats{display:grid;grid-template-columns:repeat(3,1fr);gap:.6rem}.stat{background:#0b1427;border-radius:.75rem;padding:.65rem;min-width:0}.stat strong{display:block;font-size:1.18rem;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.stat span{color:var(--muted);font-size:.72rem}
.field{border-top:1px solid var(--line);padding:.9rem 0}.field:first-of-type{border-top:0;padding-top:0}.switch{display:flex;gap:.8rem;align-items:center;cursor:pointer}.switch input{accent-color:var(--accent);width:1.3rem;height:1.3rem;flex:0 0 auto}.label{font-weight:650}.hint{display:block;color:var(--muted);font-size:.82rem;margin:.2rem 0 0 2.1rem}.two{display:grid;grid-template-columns:1fr 1fr;gap:.75rem}.offsets{display:grid;grid-template-columns:repeat(4,1fr);gap:.55rem}.input-label{display:block;color:var(--muted);font-size:.83rem;font-weight:650}.input-label input,.input-label select{width:100%;margin-top:.35rem;border:1px solid var(--line);border-radius:.65rem;background:#0b1427;color:var(--text);font:inherit;padding:.7rem}
button{border:0;border-radius:.75rem;padding:.8rem 1rem;font:inherit;font-weight:750;cursor:pointer}button.primary{width:100%;background:var(--accent);color:#072016;margin-top:.25rem}button.secondary{background:#233555;color:var(--text)}button:active{transform:translateY(1px)}.notice{min-height:1.2rem;margin:.8rem .1rem 0;color:var(--muted);font-size:.9rem}.notice.ok{color:var(--accent)}.notice.error{color:var(--danger)}.device{color:var(--muted);font-size:.78rem;margin:.75rem 0 0;overflow-wrap:anywhere}
.zone-actions{display:grid;grid-template-columns:1fr 1fr;gap:.6rem;margin:.8rem 0}.zone-actions button{width:100%}.zone-row{display:grid;grid-template-columns:1fr auto;gap:.65rem;align-items:center;border-top:1px solid var(--line);padding:.75rem 0}.zone-row:first-child{border-top:0}.zone-name{font-weight:700;overflow-wrap:anywhere}.zone-edit{display:flex;gap:.4rem;align-items:center}.zone-edit input[type=number]{width:5.2rem;border:1px solid var(--line);border-radius:.5rem;background:#0b1427;color:var(--text);font:inherit;padding:.5rem}.danger{background:#5b2934;color:#ffdce3}
@media(max-width:520px){.stats{gap:.4rem}.stat{padding:.5rem}.stat strong{font-size:1rem}.two,.zone-row{grid-template-columns:1fr}.offsets{grid-template-columns:repeat(2,1fr)}.zone-edit{flex-wrap:wrap}}
</style>
<body><main class=app>
<header class=hero><div><p class=eyebrow>comma local portal</p><h1>Speed control</h1><p class=subtle>Toyota dashboard speed-limit signs</p></div><div class=connection><i id=dot class=dot></i><span id=connection>Checking</span></div></header>
<section class=card><h2>Live status</h2><p id=source>Waiting for a speed-limit update.</p><div class=stats><div class=stat><strong id=detected>—</strong><span>Detected sign</span></div><div class=stat><strong id=accepted>—</strong><span>Accepted limit</span></div><div class=stat><strong id=cap>—</strong><span>Active cap</span></div></div><p class=device id=device>Device information unavailable</p></section>
<section class=card><h2>Personal Speed Zones</h2><p>Mark where slowing should begin, drive through the curve, then mark where normal speed should resume.</p>
<div class=two><label class=input-label>Target speed (mph)<input id=zone-target type=number inputmode=decimal min=12 max=90 value=25></label><div><span class=input-label>Comma GPS</span><strong id=zone-gps>Checking</strong></div></div>
<div class=field><label class=switch><input id=zone-lowest type=checkbox><span class=label>Use lowest recorded speed</span></label><span class=hint>Save the lowest speed measured between the two markers.</span></div>
<div class=zone-actions><button class=secondary id=zone-start>Mark slowdown</button><button class=secondary id=zone-end>Mark resume</button><button class=secondary id=zone-cancel>Cancel recording</button><button class=danger id=zone-clear>Erase all zones</button></div>
<p id=zone-state class=subtle>Not recording.</p><p id=zone-notice class=notice aria-live=polite></p><div id=zone-list></div></section>
<section class=card><h2>Toyota RSA controller</h2><p>Accept the Corolla dashboard sign and apply it as an openpilot speed cap.</p>
<div class=field><label class=switch><input id=enabled type=checkbox><span class=label>Enable speed-limit controller</span></label></div>
<div class=field><label class=switch><input id=lower type=checkbox><span class=label>Accept lower limits automatically</span></label></div>
<div class=field><label class=switch><input id=higher type=checkbox><span class=label>Accept higher limits automatically</span></label></div>
<div class=field><label class=input-label>Absolute maximum (mph)<input id=max type=number inputmode=decimal step=.1 placeholder="No maximum"></label></div>
</section>
<section class=card><h2>Sign-specific offsets</h2><p>Each offset is used only when that exact dashboard sign is detected. Leave a value at 0 for no adjustment.</p><div class=offsets>
<label class=input-label>20 mph<input id=offset-20 type=number inputmode=decimal step=.1></label><label class=input-label>25 mph<input id=offset-25 type=number inputmode=decimal step=.1></label><label class=input-label>30 mph<input id=offset-30 type=number inputmode=decimal step=.1></label><label class=input-label>40 mph<input id=offset-40 type=number inputmode=decimal step=.1></label>
<label class=input-label>50 mph<input id=offset-50 type=number inputmode=decimal step=.1></label><label class=input-label>60 mph<input id=offset-60 type=number inputmode=decimal step=.1></label><label class=input-label>70 mph<input id=offset-70 type=number inputmode=decimal step=.1></label><label class=input-label>75 mph<input id=offset-75 type=number inputmode=decimal step=.1></label>
</div></section>
<section class=card><h2>Driving controls</h2><p>These settings match controls available on the comma.</p>
<div class=field><label class=switch><input id=always-on-dm type=checkbox><span class=label>Always-on driver monitoring</span></label><span class=hint>Keep monitoring active while openpilot is not engaged.</span></div>
<div class=field><label class=switch><input id=ldw type=checkbox><span class=label>Lane departure warnings</span></label></div>
<div class=field><label class=switch><input id=accelerator-disengage type=checkbox><span class=label>Disengage on accelerator</span></label></div>
<div class=field><label class=input-label>Driving personality<select id=personality><option value=aggressive>Aggressive</option><option value=standard>Standard</option><option value=relaxed>Relaxed</option></select></label></div>
<div class=field><label class=switch><input id=portal-enabled type=checkbox><span class=label>Keep local phone portal available</span></label><span class=hint>Turning this off closes this page after it saves.</span></div>
</section>
<button class=secondary id=refresh>Refresh status</button><button class=primary id=save>Save changes</button><p id=notice class=notice aria-live=polite></p>
</main><script src=/portal.js></script></body></html>"""

SCRIPT = """const $=id=>document.getElementById(id),MPS_TO_MPH=2.236936,SIGNS=[20,25,30,40,50,60,70,75];let loaded=false,revision='',zoneRevision='';
const mph=value=>value===null||value===undefined?'—':Math.round(value*MPS_TO_MPH*10)/10+' mph';
function notice(message,kind=''){let el=$('notice');el.textContent=message;el.className='notice '+kind}
function zoneNotice(message,kind=''){let el=$('zone-notice');el.textContent=message;el.className='notice '+kind}
function renderZones(data){let config=data.config||{zones:[]},runtime=data.runtime||{},recorder=data.recorder||{};zoneRevision=data.revision||'';$('zone-gps').textContent=data.gps_ready?'Ready':'Unavailable';$('zone-state').textContent=recorder.recording?'Recording '+Math.round(recorder.target_mph)+' mph zone'+(recorder.use_lowest_speed?' using lowest speed.':'.'):(runtime.active?'Zone active: '+mph(runtime.effective_cap_mps):'Not recording. '+(config.zones||[]).length+' saved zone(s).');let list=$('zone-list');list.replaceChildren();(config.zones||[]).forEach(zone=>{let row=document.createElement('div');row.className='zone-row';let name=document.createElement('div');name.className='zone-name';name.textContent=zone.id;let edit=document.createElement('div');edit.className='zone-edit';let enabled=document.createElement('input');enabled.type='checkbox';enabled.checked=!!zone.enabled;let target=document.createElement('input');target.type='number';target.min=12;target.max=90;target.value=zone.target_mph;let save=document.createElement('button');save.className='secondary';save.textContent='Save';save.onclick=()=>zoneAction({action:'update',zone_id:zone.id,enabled:enabled.checked,target_mph:Number(target.value),revision:zoneRevision});let remove=document.createElement('button');remove.className='danger';remove.textContent='Delete';remove.onclick=()=>{if(confirm('Delete '+zone.id+'?'))zoneAction({action:'delete',zone_id:zone.id,revision:zoneRevision})};edit.append(enabled,target,save,remove);row.append(name,edit);list.append(row)})}
function status(data){let settings=data.settings||{},rsa=data.rsa||{},zones=data.personal_speed_zones||{},device=data.device||{},connected=!!rsa.available||!!(zones.runtime||{}).available;loaded=true;revision=data.settings_revision||'';
  $('dot').className='dot '+(connected?'ok':'');$('connection').textContent=connected?'Connected':'Not connected';
  $('detected').textContent=mph(rsa.detected_limit_mps);$('accepted').textContent=mph(rsa.accepted_limit_mps);$('cap').textContent=mph(rsa.effective_cap_mps);
  $('source').textContent=rsa.source_fresh?'Dashboard RSA sign is fresh.':rsa.source_state?'RSA source: '+rsa.source_state+'.':'Waiting for a dashboard RSA sign.';
  $('device').textContent=device.version?device.version+(device.branch?' · '+device.branch:''):'Device information unavailable';
  $('enabled').checked=!!settings.enabled;$('lower').checked=!!settings.auto_accept_lower;$('higher').checked=!!settings.auto_accept_higher;
  SIGNS.forEach(sign=>$('offset-'+sign).value=((settings['offset_'+sign+'_mps']||0)*MPS_TO_MPH).toFixed(1));$('max').value=settings.absolute_max_mps===null||settings.absolute_max_mps===undefined?'':(settings.absolute_max_mps*MPS_TO_MPH).toFixed(1);
  $('always-on-dm').checked=!!settings.always_on_driver_monitoring;$('ldw').checked=!!settings.lane_departure_warnings;$('accelerator-disengage').checked=!!settings.disengage_on_accelerator;
  $('personality').value=settings.driving_personality||'standard';$('portal-enabled').checked=!!settings.local_phone_portal;
  renderZones(zones);
}
async function api(path,options={}){let response=await fetch(path,options),data=await response.json();if(!response.ok)throw Error(data.error||'Request failed');return data}
async function load(){notice('');try{status(await api('/api/status'))}catch(error){notice(error.message,'error');$('connection').textContent='Unavailable'}}
async function zoneAction(payload){zoneNotice('Sending request…');try{let data=await api('/api/personal-speed-zones',{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});status(data);zoneNotice(payload.action==='mark_start'?'Slowdown point saved.':payload.action==='mark_end'?'Zone saved.':'Zone settings updated.','ok')}catch(error){zoneNotice(error.message,'error')}}
async function save(){try{if(!loaded)throw Error('Load settings before saving.');let maximum=$('max').value,payload={
  enabled:$('enabled').checked,auto_accept_lower:$('lower').checked,auto_accept_higher:$('higher').checked,
  absolute_max_mps:maximum===''?null:Number(maximum)/MPS_TO_MPH,
  always_on_driver_monitoring:$('always-on-dm').checked,lane_departure_warnings:$('ldw').checked,
  disengage_on_accelerator:$('accelerator-disengage').checked,driving_personality:$('personality').value,
  local_phone_portal:$('portal-enabled').checked};SIGNS.forEach(sign=>payload['offset_'+sign+'_mps']=Number($('offset-'+sign).value)/MPS_TO_MPH);let data=await api('/api/settings',{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({settings:payload,revision})});status(data);notice('Saved to your comma.','ok')}catch(error){notice(error.message,'error')}}
$('refresh').addEventListener('click',load);$('save').addEventListener('click',save);$('zone-start').addEventListener('click',()=>zoneAction({action:'mark_start',target_mph:Number($('zone-target').value),use_lowest_speed:$('zone-lowest').checked}));$('zone-end').addEventListener('click',()=>zoneAction({action:'mark_end'}));$('zone-cancel').addEventListener('click',()=>zoneAction({action:'cancel'}));$('zone-clear').addEventListener('click',()=>{if(confirm('Erase every saved Personal Speed Zone?'))zoneAction({action:'clear',confirm:'erase all',revision:zoneRevision})});load();"""


class RuntimeState:
  """Drain messaging sockets on one thread and provide atomic portal snapshots."""

  def __init__(self):
    self._lock = threading.RLock()
    self._rsa = {"available": False}
    self._rsa_updated_at = None
    self._zone = {"available": False, "source_state": "controller_unavailable"}
    self._zone_updated_at = None
    self._speed_mps = None
    self._speed_updated_at = None
    self._gps = {service: GPSAdapter(service) for service in ("gpsLocation", "gpsLocationExternal")}
    self._recorder = zone_store.Recorder()
    self._stop = threading.Event()
    self._thread = threading.Thread(target=self._run, daemon=True, name="portal-runtime")
    self._thread.start()

  def _run(self):
    rsa_socket = messaging.sub_sock("speedLimitState", conflate=True)
    zone_socket = messaging.sub_sock("personalSpeedZoneState", conflate=True)
    gps_sockets = {service: messaging.sub_sock(service, conflate=True) for service in self._gps}
    car_socket = messaging.sub_sock("carState", conflate=True)
    while not self._stop.is_set():
      now = time.monotonic()
      rsa_message = messaging.recv_one_or_none(rsa_socket)
      zone_message = messaging.recv_one_or_none(zone_socket)
      gps_messages = {service: messaging.recv_one_or_none(socket) for service, socket in gps_sockets.items()}
      car_message = messaging.recv_one_or_none(car_socket)
      with self._lock:
        if rsa_message is not None and rsa_message.valid:
          state = rsa_message.speedLimitState
          self._rsa = {
            "available": True,
            "source_state": str(state.sourceState),
            "source_fresh": bool(state.sourceFresh),
            "detected_limit_mps": state.detectedLimitMps if state.hasDetectedLimit else None,
            "accepted_limit_mps": state.acceptedLimitMps if state.hasAcceptedLimit else None,
            "effective_cap_mps": state.effectiveCapMps if state.restrictionActive else None,
          }
          self._rsa_updated_at = now
        if zone_message is not None and zone_message.valid:
          state = zone_message.personalSpeedZoneState
          self._zone = {
            "available": True,
            "source_state": str(state.sourceState),
            "gps_fresh": bool(state.gpsFresh),
            "active": bool(state.restrictionActive),
            "effective_cap_mps": state.effectiveCapMps if state.restrictionActive else None,
            "target_mps": state.targetMps if state.hasTarget else None,
            "zone_count": int(state.zoneCount),
            "active_zone_count": int(state.activeZoneCount),
          }
          self._zone_updated_at = now
        for service, message in gps_messages.items():
          self._gps[service].observe(message, now)
        if car_message is not None and car_message.valid:
          self._speed_mps = max(0.0, float(car_message.carState.vEgo))
          self._speed_updated_at = now
          self._recorder.observe_speed(self._speed_mps)
        self._recorder.expire(now)
      time.sleep(0.05)

  def close(self):
    self._stop.set()
    self._thread.join(timeout=1.0)

  @staticmethod
  def _expire(value, updated_at, now):
    result = dict(value)
    result["age_s"] = None if updated_at is None else now - updated_at
    if result["age_s"] is None or result["age_s"] > 3.0:
      result.update({"available": False, "source_state": "controller_unavailable"})
    return result

  def snapshot(self):
    now = time.monotonic()
    with self._lock:
      return {
        "rsa": self._expire(self._rsa, self._rsa_updated_at, now),
        "zone": self._expire(self._zone, self._zone_updated_at, now),
        "gps_ready": self._current_gps(now) is not None,
        "recorder": self._recorder.status(now),
      }

  def _current_gps(self, now):
    samples = [adapter.current(now) for adapter in self._gps.values()]
    return max((sample for sample in samples if sample is not None), key=lambda sample: sample.received_at, default=None)

  def zone_action(self, payload):
    if type(payload) is not dict or type(payload.get("action")) is not str:
      raise ValueError("zone action is required")
    action = payload["action"]
    now = time.monotonic()
    with self._lock:
      gps = self._current_gps(now)
      if action == "mark_start":
        if gps is None:
          raise ValueError("fresh comma GPS is unavailable")
        speed = self._speed_mps if self._speed_updated_at is not None and now - self._speed_updated_at <= 1.0 else None
        _, revision = zone_store.snapshot()
        self._recorder.begin(gps.as_position(), payload.get("target_mph"), payload.get("use_lowest_speed", False), speed, now, revision)
      elif action == "mark_end":
        if gps is None:
          raise ValueError("fresh comma GPS is unavailable")
        self._recorder.finish(gps.as_position())
      elif action == "cancel":
        self._recorder.cancel()
      elif action == "update":
        if type(payload.get("revision")) is not str:
          raise ValueError("zone revision is required")
        zone_store.update_zone(
          payload.get("zone_id"), enabled=payload.get("enabled"), target_mph=payload.get("target_mph"), expected_revision=payload.get("revision")
        )
      elif action == "delete":
        if type(payload.get("revision")) is not str:
          raise ValueError("zone revision is required")
        zone_store.delete_zone(payload.get("zone_id"), expected_revision=payload.get("revision"))
      elif action == "clear":
        if type(payload.get("revision")) is not str:
          raise ValueError("zone revision is required")
        if payload.get("confirm") != "erase all":
          raise ValueError("erase confirmation is required")
        zone_store.clear_zones(expected_revision=payload.get("revision"))
        self._recorder.cancel()
      else:
        raise ValueError("unknown zone action")


class Portal:
  def __init__(self, params=None, runtime_state=None):
    self.params = Params() if params is None else params
    self.runtime_state = RuntimeState() if runtime_state is None else runtime_state

  def status(self):
    settings = read_settings(self.params)
    runtime = self.runtime_state.snapshot()
    zone_config, zone_revision = zone_store.snapshot()
    return {
      "settings": settings,
      "settings_revision": settings_revision(settings),
      "rsa": runtime["rsa"],
      "personal_speed_zones": {
        "config": zone_config,
        "revision": zone_revision,
        "runtime": runtime["zone"],
        "gps_ready": runtime["gps_ready"],
        "recorder": runtime["recorder"],
      },
      "device": {
        "version": self.params.get("Version", return_default=True),
        "branch": self.params.get("GitBranch", return_default=True),
        "commit": self.params.get("GitCommit", return_default=True),
      },
    }

  def update_settings(self, payload):
    if type(payload) is not dict or set(payload) != {"settings", "revision"}:
      raise ValueError("settings and revision are required")
    apply_settings(self.params, payload["settings"], payload["revision"])
    return self.status()

  def update_zones(self, payload):
    self.runtime_state.zone_action(payload)
    return self.status()

  def close(self):
    close = getattr(self.runtime_state, "close", None)
    if close is not None:
      close()


def handler_factory(portal):
  class Handler(BaseHTTPRequestHandler):
    def setup(self):
      super().setup()
      self.connection.settimeout(5)

    def _send(self, status, payload, content_type="application/json"):
      data = payload.encode() if isinstance(payload, str) else json.dumps(payload, allow_nan=False).encode()
      self.send_response(status)
      self.send_header("Content-Type", content_type)
      self.send_header("Content-Length", str(len(data)))
      self.send_header("Cache-Control", "no-store")
      self.send_header("X-Content-Type-Options", "nosniff")
      self.send_header("X-Frame-Options", "DENY")
      self.send_header("Content-Security-Policy", "default-src 'self'; style-src 'self' 'unsafe-inline'; script-src 'self'")
      self.end_headers()
      self.wfile.write(data)

    def do_GET(self):
      if self.path == "/":
        self._send(HTTPStatus.OK, PAGE, "text/html; charset=utf-8")
      elif self.path == "/portal.js":
        self._send(HTTPStatus.OK, SCRIPT, "application/javascript; charset=utf-8")
      elif self.path == "/api/status":
        self._send(HTTPStatus.OK, portal.status())
      else:
        self._send(HTTPStatus.NOT_FOUND, {"error": "not found"})

    def do_PUT(self):
      if self.path not in {"/api/settings", "/api/personal-speed-zones"}:
        self._send(HTTPStatus.NOT_FOUND, {"error": "not found"})
        return
      try:
        size = int(self.headers.get("Content-Length", "0"))
        if not 0 < size <= 4096:
          raise ValueError("request body must be 1..4096 bytes")
        payload = json.loads(self.rfile.read(size))
        result = portal.update_settings(payload) if self.path == "/api/settings" else portal.update_zones(payload)
        self._send(HTTPStatus.OK, result)
      except (PermissionError, SettingsConflict, zone_store.ZoneConflict) as exc:
        self._send(HTTPStatus.CONFLICT, {"error": str(exc)})
      except (TypeError, ValueError, json.JSONDecodeError) as exc:
        self._send(HTTPStatus.BAD_REQUEST, {"error": str(exc)})

    def log_message(self, *_):
      pass

  return Handler


def main():
  params = Params()
  server = None
  portal = None
  while True:
    enabled = params.get_bool(ENABLED_PARAM)
    if enabled and server is None:
      portal = Portal(params)
      server = LocalPortalServer(("0.0.0.0", PORT), handler_factory(portal))
      threading.Thread(target=server.serve_forever, daemon=True).start()
    elif not enabled and server is not None:
      server.shutdown()
      server.server_close()
      portal.close()
      portal = None
      server = None
    time.sleep(1)


if __name__ == "__main__":
  main()
