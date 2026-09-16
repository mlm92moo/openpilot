#!/usr/bin/env python3
"""Local-network phone portal for speed-limit settings."""
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import threading
import time

from openpilot.common.params import Params
import openpilot.cereal.messaging as messaging

from openpilot.custom.speed_limit.portal_settings import apply_settings, read_settings

PORT = 8080
ENABLED_PARAM = "SpeedLimitPortalEnabled"

PAGE = """<!doctype html><meta name=viewport content='width=device-width,initial-scale=1'>
<title>comma speed limit</title><style>body{font:18px system-ui;margin:auto;max-width:34rem;padding:1rem}input,button{font:inherit;padding:.5rem;margin:.25rem 0;width:100%}label{display:block;margin-top:.75rem}pre{white-space:pre-wrap;background:#eee;padding:.75rem}</style>
<h1>Speed limit</h1><button id=refresh>Refresh</button><pre id=status>Not connected</pre>
<label><input id=enabled type=checkbox> Enable Toyota RSA controller</label><label><input id=lower type=checkbox> Automatically accept lower limits</label><label><input id=higher type=checkbox> Automatically accept higher limits</label><label>Offset (mph)<input id=offset type=number step=.1></label><label>Absolute maximum (mph; blank disables)<input id=max type=number step=.1></label><button id=save>Save while offroad</button>
<script src=/portal.js></script>"""

SCRIPT = """const $=id=>document.getElementById(id),MPS_TO_MPH=2.236936;
async function api(path,options={}){let r=await fetch(path,options);let j=await r.json();if(!r.ok)throw Error(j.error);return j}
async function load(){try{let j=await api('/api/status');$('status').textContent=JSON.stringify(j,null,2);$('enabled').checked=j.settings.enabled;$('lower').checked=j.settings.auto_accept_lower;$('higher').checked=j.settings.auto_accept_higher;$('offset').value=(j.settings.offset_mps*MPS_TO_MPH).toFixed(1);$('max').value=j.settings.absolute_max_mps===null?'':(j.settings.absolute_max_mps*MPS_TO_MPH).toFixed(1)}catch(e){$('status').textContent=e}}
async function save(){try{let v=$('max').value;let j=await api('/api/settings',{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({enabled:$('enabled').checked,auto_accept_lower:$('lower').checked,auto_accept_higher:$('higher').checked,offset_mps:Number($('offset').value)/MPS_TO_MPH,absolute_max_mps:v===''?null:Number(v)/MPS_TO_MPH})});$('status').textContent=JSON.stringify(j,null,2)}catch(e){$('status').textContent=e}}
$('refresh').addEventListener('click', load);$('save').addEventListener('click', save);"""


class RuntimeState:
  def __init__(self):
    self._socket = messaging.sub_sock("speedLimitState", conflate=True)
    self._lock = threading.Lock()
    self._value = {"available": False}

  def snapshot(self):
    with self._lock:
      for message in messaging.drain_sock(self._socket):
        if message.which() == "speedLimitState":
          state = message.speedLimitState
          self._value = {
            "available": bool(message.valid), "source_state": str(state.sourceState),
            "source_fresh": bool(state.sourceFresh), "detected_limit_mps": state.detectedLimitMps if state.hasDetectedLimit else None,
            "accepted_limit_mps": state.acceptedLimitMps if state.hasAcceptedLimit else None,
            "effective_cap_mps": state.effectiveCapMps if state.restrictionActive else None,
          }
      return dict(self._value)


class Portal:
  def __init__(self, params=None, runtime_state=None):
    self.params = Params() if params is None else params
    self.runtime_state = RuntimeState() if runtime_state is None else runtime_state

  def status(self):
    return {"settings": read_settings(self.params), "rsa": self.runtime_state.snapshot(),
            "device": {"version": self.params.get("Version", return_default=True),
                       "branch": self.params.get("GitBranch", return_default=True),
                       "commit": self.params.get("GitCommit", return_default=True)}}

  def update_settings(self, payload):
    return {"settings": apply_settings(self.params, payload, self.params.get_bool("IsOffroad")), "rsa": self.runtime_state.snapshot()}


def handler_factory(portal):
  class Handler(BaseHTTPRequestHandler):
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
      if self.path != "/api/settings":
        self._send(HTTPStatus.NOT_FOUND, {"error": "not found"})
        return
      try:
        size = int(self.headers.get("Content-Length", "0"))
        if not 0 < size <= 4096:
          raise ValueError("request body must be 1..4096 bytes")
        payload = json.loads(self.rfile.read(size))
        self._send(HTTPStatus.OK, portal.update_settings(payload))
      except PermissionError as exc:
        self._send(HTTPStatus.CONFLICT, {"error": str(exc)})
      except (TypeError, ValueError, json.JSONDecodeError) as exc:
        self._send(HTTPStatus.BAD_REQUEST, {"error": str(exc)})

    def log_message(self, *_):
      pass
  return Handler


def main():
  params = Params()
  server = None
  while True:
    enabled = params.get_bool(ENABLED_PARAM)
    if enabled and server is None:
      portal = Portal(params)
      server = ThreadingHTTPServer(("0.0.0.0", PORT), handler_factory(portal))
      threading.Thread(target=server.serve_forever, daemon=True).start()
    elif not enabled and server is not None:
      server.shutdown()
      server.server_close()
      server = None
    time.sleep(1)


if __name__ == "__main__":
  main()
