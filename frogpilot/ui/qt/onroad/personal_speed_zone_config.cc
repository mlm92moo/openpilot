#include "frogpilot/ui/qt/onroad/personal_speed_zone_config.h"

#include <algorithm>
#include <cmath>

#include <QDateTime>
#include <QFile>
#include <QJsonArray>
#include <QJsonDocument>
#include <QJsonParseError>
#include <QSaveFile>

namespace {
constexpr double EARTH_RADIUS_M = 6371000.0;
constexpr double DUPLICATE_ZONE_DISTANCE_M = 12.0;
constexpr double DUPLICATE_ZONE_BEARING_DEG = 20.0;

double markerDistanceMeters(const QJsonObject &first, const QJsonObject &second) {
  const double lat1 = first.value("latitude").toDouble() * M_PI / 180.0;
  const double lat2 = second.value("latitude").toDouble() * M_PI / 180.0;
  const double d_lat = lat2 - lat1;
  const double d_lon = (second.value("longitude").toDouble() - first.value("longitude").toDouble()) * M_PI / 180.0;
  const double a = std::sin(d_lat / 2.0) * std::sin(d_lat / 2.0) +
                   std::cos(lat1) * std::cos(lat2) * std::sin(d_lon / 2.0) * std::sin(d_lon / 2.0);
  return EARTH_RADIUS_M * 2.0 * std::atan2(std::sqrt(std::clamp(a, 0.0, 1.0)), std::sqrt(std::clamp(1.0 - a, 0.0, 1.0)));
}

double markerBearingDifference(const QJsonObject &first, const QJsonObject &second) {
  const double difference = std::fmod(std::abs(first.value("bearing").toDouble() - second.value("bearing").toDouble()), 360.0);
  return std::min(difference, 360.0 - difference);
}

bool isDuplicateRecordedZone(const QJsonObject &zone, const QJsonObject &start, const QJsonObject &end) {
  if (!zone.value("recorded_from_ui").toBool()) return false;
  const QJsonObject existing_start = zone.value("start").toObject();
  const QJsonObject existing_end = zone.value("end").toObject();
  return markerDistanceMeters(existing_start, start) <= DUPLICATE_ZONE_DISTANCE_M &&
         markerDistanceMeters(existing_end, end) <= DUPLICATE_ZONE_DISTANCE_M &&
         markerBearingDifference(existing_start, start) <= DUPLICATE_ZONE_BEARING_DEG &&
         markerBearingDifference(existing_end, end) <= DUPLICATE_ZONE_BEARING_DEG;
}
}  // namespace

bool appendPersonalSpeedZone(const QString &config_path, const QJsonObject &start, const QJsonObject &end,
                             int target_mph, QString *zone_id) {
  QJsonObject config;
  QFile input(config_path);
  if (input.exists()) {
    if (!input.open(QIODevice::ReadOnly)) return false;

    QJsonParseError parse_error;
    const QJsonDocument existing = QJsonDocument::fromJson(input.readAll(), &parse_error);
    if (parse_error.error != QJsonParseError::NoError || !existing.isObject()) return false;
    config = existing.object();
    if (config.contains("zones") && !config.value("zones").isArray()) return false;
  }

  QJsonArray zones = config.value("zones").toArray();
  QString id = "recorded-" + QDateTime::currentDateTimeUtc().toString("yyyyMMdd-hhmmss-zzz");
  QJsonObject new_zone {
    {"id", id},
    {"enabled", true},
    {"apply_target", true},
    {"recorded_from_ui", true},
    {"target_mph", std::clamp(target_mph, 12, 90)},
    {"start", start},
    {"end", end},
    {"corridor_width_m", 20},
    {"gate_arm_distance_m", 20},
    {"heading_tolerance_deg", 25},
  };
  bool replaced_duplicate = false;
  for (int index = 0; index < zones.size(); ++index) {
    const QJsonObject existing_zone = zones.at(index).toObject();
    if (isDuplicateRecordedZone(existing_zone, start, end)) {
      id = existing_zone.value("id").toString(id);
      new_zone["id"] = id;
      zones.replace(index, new_zone);
      replaced_duplicate = true;
      break;
    }
  }
  if (!replaced_duplicate) zones.append(new_zone);
  config["zones"] = zones;
  if (!config.contains("apply_target")) config["apply_target"] = false;

  QSaveFile output(config_path);
  if (!output.open(QIODevice::WriteOnly)) return false;
  if (output.write(QJsonDocument(config).toJson(QJsonDocument::Indented)) < 0) return false;
  if (!output.commit()) return false;

  if (zone_id != nullptr) *zone_id = id;
  return true;
}

bool clearPersonalSpeedZones(const QString &config_path) {
  const QJsonObject config {
    {"apply_target", false},
    {"zones", QJsonArray()},
  };

  QSaveFile output(config_path);
  if (!output.open(QIODevice::WriteOnly)) return false;
  if (output.write(QJsonDocument(config).toJson(QJsonDocument::Indented)) < 0) return false;
  return output.commit();
}

int selectPersonalSpeedZoneTargetMph(int configured_target_mph, bool use_current_speed, double current_speed_mps) {
  int target_mph = configured_target_mph;
  if (use_current_speed && std::isfinite(current_speed_mps)) {
    constexpr double meters_per_second_to_mph = 2.2369362921;
    target_mph = std::lround(current_speed_mps * meters_per_second_to_mph);
  }
  return std::clamp(target_mph, 12, 90);
}
