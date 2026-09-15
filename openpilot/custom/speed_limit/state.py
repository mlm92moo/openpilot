"""Convert controller output to the fixed typed-service representation."""
import math


def _optional_float(value, name):
  if value is None:
    return False, 0.0
  if type(value) not in (int, float) or not math.isfinite(value):
    raise ValueError(f"{name} must be a finite number or None")
  return True, float(value)


def service_fields(result):
  """Return only fields represented in `SpeedLimitState`.

  Cap'n Proto scalar fields have no `None`, so each optional speed has a
  companion `has...` flag. This boundary keeps that conversion out of policy.
  """
  required = {"enabled", "control_eligible", "source_state", "source_revision",
              "detected_limit_mps", "accepted_limit_mps", "effective_cap_mps"}
  if type(result) is not dict or required - result.keys():
    raise ValueError("incomplete controller result")
  if type(result["enabled"]) is not bool or type(result["control_eligible"]) is not bool:
    raise ValueError("enabled and control_eligible must be boolean")
  if type(result["source_state"]) is not str or type(result["source_revision"]) is not int or result["source_revision"] < 0:
    raise ValueError("invalid source metadata")
  has_detected, detected = _optional_float(result["detected_limit_mps"], "detected_limit_mps")
  has_accepted, accepted = _optional_float(result["accepted_limit_mps"], "accepted_limit_mps")
  _, effective = _optional_float(result["effective_cap_mps"], "effective_cap_mps")
  return {
    "enabled": result["enabled"],
    "controlEligible": result["control_eligible"],
    "sourceFresh": bool(result.get("detected_limit_fresh", False)),
    "sourceRevision": result["source_revision"],
    "sourceState": result["source_state"],
    "hasDetectedLimit": has_detected,
    "detectedLimitMps": detected,
    "hasAcceptedLimit": has_accepted,
    "acceptedLimitMps": accepted,
    "effectiveCapMps": effective,
  }
