#include "catch2/catch.hpp"

#include <QFile>
#include <QJsonArray>
#include <QJsonDocument>
#include <QTemporaryDir>

#include "frogpilot/ui/qt/onroad/personal_speed_zone_config.h"

namespace {
QJsonObject marker(double latitude, double longitude, double bearing) {
  return {{"latitude", latitude}, {"longitude", longitude}, {"bearing", bearing}};
}

QJsonObject readConfig(const QString &path) {
  QFile file(path);
  REQUIRE(file.open(QIODevice::ReadOnly));
  const QJsonDocument document = QJsonDocument::fromJson(file.readAll());
  REQUIRE(document.isObject());
  return document.object();
}
}  // namespace

TEST_CASE("Personal Speed Zones: touchscreen recording is active") {
  QTemporaryDir directory;
  REQUIRE(directory.isValid());
  const QString path = directory.filePath("zones.json");

  QString zone_id;
  REQUIRE(appendPersonalSpeedZone(path, marker(37.0, -122.0, 5.0), marker(37.1, -122.1, 15.0), 5, &zone_id));

  const QJsonObject config = readConfig(path);
  CHECK(config.value("apply_target").toBool() == false);
  const QJsonObject zone = config.value("zones").toArray().first().toObject();
  CHECK(zone.value("id").toString() == zone_id);
  CHECK(zone.value("enabled").toBool());
  CHECK(zone.value("apply_target").toBool());
  CHECK(zone.value("recorded_from_ui").toBool());
  CHECK(zone.value("target_mph").toInt() == 12);
}

TEST_CASE("Personal Speed Zones: recording preserves existing zones") {
  QTemporaryDir directory;
  REQUIRE(directory.isValid());
  const QString path = directory.filePath("zones.json");
  QFile file(path);
  REQUIRE(file.open(QIODevice::WriteOnly));
  file.write(R"({"apply_target":false,"zones":[{"id":"existing"}]})");
  file.close();

  REQUIRE(appendPersonalSpeedZone(path, marker(37.0, -122.0, 0.0), marker(37.1, -122.1, 0.0), 25));
  const QJsonArray zones = readConfig(path).value("zones").toArray();
  REQUIRE(zones.size() == 2);
  CHECK(zones.first().toObject().value("id").toString() == "existing");
}

TEST_CASE("Personal Speed Zones: re-recording the same route updates instead of duplicating") {
  QTemporaryDir directory;
  REQUIRE(directory.isValid());
  const QString path = directory.filePath("zones.json");
  const QJsonObject start = marker(37.0, -122.0, 0.0);
  const QJsonObject end = marker(37.001, -122.0, 0.0);

  QString original_id;
  REQUIRE(appendPersonalSpeedZone(path, start, end, 25, &original_id));
  QString updated_id;
  REQUIRE(appendPersonalSpeedZone(path, marker(37.00005, -122.0, 2.0), marker(37.00105, -122.0, 2.0), 30, &updated_id));

  const QJsonArray zones = readConfig(path).value("zones").toArray();
  REQUIRE(zones.size() == 1);
  CHECK(updated_id == original_id);
  CHECK(zones.first().toObject().value("target_mph").toInt() == 30);
}

TEST_CASE("Personal Speed Zones: malformed configuration is not overwritten") {
  QTemporaryDir directory;
  REQUIRE(directory.isValid());
  const QString path = directory.filePath("zones.json");
  const QByteArray malformed = R"({"zones":"not-an-array"})";
  QFile file(path);
  REQUIRE(file.open(QIODevice::WriteOnly));
  file.write(malformed);
  file.close();

  CHECK_FALSE(appendPersonalSpeedZone(path, marker(37.0, -122.0, 0.0), marker(37.1, -122.1, 0.0), 25));
  REQUIRE(file.open(QIODevice::ReadOnly));
  CHECK(file.readAll() == malformed);
}

TEST_CASE("Personal Speed Zones: clearing zones writes an empty valid configuration") {
  QTemporaryDir directory;
  REQUIRE(directory.isValid());
  const QString path = directory.filePath("zones.json");
  REQUIRE(appendPersonalSpeedZone(path, marker(37.0, -122.0, 0.0), marker(37.1, -122.1, 0.0), 25));

  REQUIRE(clearPersonalSpeedZones(path));
  const QJsonObject config = readConfig(path);
  CHECK_FALSE(config.value("apply_target").toBool());
  CHECK(config.value("zones").toArray().isEmpty());
}

TEST_CASE("Personal Speed Zones: target can use a speed captured while recording") {
  CHECK(selectPersonalSpeedZoneTargetMph(25, false, 13.4112) == 25);
  CHECK(selectPersonalSpeedZoneTargetMph(25, true, 13.4112) == 30);
  CHECK(selectPersonalSpeedZoneTargetMph(25, true, 0.0) == 12);
  CHECK(selectPersonalSpeedZoneTargetMph(25, true, 100.0) == 90);
}
