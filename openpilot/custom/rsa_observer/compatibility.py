"""Fail visibly when a native dependency differs from the audited source."""
import hashlib
import importlib.util
from pathlib import Path

SOURCE_COMMIT = "053d9c446800df38aca42b69bb99197aefbea77b"
RELEASE_COMMIT = "473eba53f280743d09c5bebc2d0613ea46883e02"
OPENDBC_COMMIT = "b4ef5e1cf406ff143fa67bdbfb154739d43279c9"

EXPECTED = {
  "opendbc.can.parser": "7290ffad36a4d9671217dcc9d3bcc98f346e5137",
  "opendbc.can.dbc": "1193660ec54fa361ff149da1f83874dd27598daa",
  "openpilot.cereal.messaging": "dcc54baeb0ff96fffc23a8bc2e8808a32fe0726e",
  "openpilot.tools.lib.logreader": "805e411b53adb56e89b9ecba35be00c400aff178",
}


def verify_runtime(mode):
  names = ["opendbc.can.parser", "opendbc.can.dbc"]
  if mode == "live":
    names.append("openpilot.cereal.messaging")
  elif mode == "rlog":
    names.append("openpilot.tools.lib.logreader")
  for name in names:
    spec = importlib.util.find_spec(name)
    if spec is None or spec.origin is None:
      raise ValueError(f"missing runtime dependency: {name}")
    content = Path(spec.origin).read_bytes()
    sha = hashlib.sha1(b"blob " + str(len(content)).encode() + b"\0" + content).hexdigest()
    if sha != EXPECTED[name]:
      raise ValueError(f"unsupported {name} revision; expected Git blob {EXPECTED[name]}, found {sha}. Re-audit before running.")
