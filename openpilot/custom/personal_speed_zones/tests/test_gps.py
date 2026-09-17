from types import SimpleNamespace

from openpilot.custom.personal_speed_zones.gps import GPSAdapter, MAX_SAMPLE_AGE_S


def message(sequence=10_000_000_000, valid=True, fix=True, horizontal=2.0, bearing_accuracy=5.0, service="gpsLocation"):
  location = SimpleNamespace(
    latitude=37.0, longitude=-122.0, bearingDeg=90.0, speed=15.0, hasFix=fix, horizontalAccuracy=horizontal, bearingAccuracyDeg=bearing_accuracy
  )
  return SimpleNamespace(valid=valid, logMonoTime=sequence, which=lambda: service, **{service: location})


def test_adapter_accepts_each_valid_message_once_and_expires():
  adapter = GPSAdapter("gpsLocation")
  sample = adapter.observe(message(), 10.0)
  assert sample is not None
  assert adapter.observe(message(), 10.1) is None
  assert adapter.current(10.0 + MAX_SAMPLE_AGE_S) is not None
  assert adapter.current(10.0 + MAX_SAMPLE_AGE_S + 0.01) is None


def test_adapter_rejects_bad_fix_accuracy_and_heading():
  for candidate in (message(fix=False), message(horizontal=51), message(bearing_accuracy=91)):
    assert GPSAdapter("gpsLocation").observe(candidate, 10.0) is None


def test_adapter_rejects_a_delayed_message():
  assert GPSAdapter("gpsLocation").observe(message(sequence=1_000_000_000), 3.0) is None


def test_qcom_unknown_horizontal_accuracy_is_explicit_but_external_requires_accuracy():
  qcom = GPSAdapter("gpsLocation").observe(message(horizontal=0), 10.0)
  assert qcom is not None
  assert qcom.horizontal_accuracy_known is False
  external_message = message(horizontal=0, service="gpsLocationExternal")
  assert GPSAdapter("gpsLocationExternal").observe(external_message, 10.0) is None


def test_explicit_fix_loss_clears_cached_sample_immediately():
  adapter = GPSAdapter("gpsLocation")
  assert adapter.observe(message(), 10.0) is not None
  assert adapter.observe(message(sequence=10_100_000_000, fix=False), 10.1) is None
  assert adapter.current(10.1) is None
