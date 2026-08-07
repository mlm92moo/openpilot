#include "frogpilot/ui/qt/onroad/personal_speed_zone_config.h"

#include <algorithm>

#include <QDateTime>
#include <QFile>
#include <QJsonArray>
#include <QJsonDocument>
#include <QJsonParseError>
#include <QSaveFile>

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
  const QString id = "recorded-" + QDateTime::currentDateTimeUtc().toString("yyyyMMdd-hhmmss-zzz");
  zones.append(QJsonObject {
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
  });
  config["zones"] = zones;
  if (!config.contains("apply_target")) config["apply_target"] = false;

  QSaveFile output(config_path);
  if (!output.open(QIODevice::WriteOnly)) return false;
  if (output.write(QJsonDocument(config).toJson(QJsonDocument::Indented)) < 0) return false;
  if (!output.commit()) return false;

  if (zone_id != nullptr) *zone_id = id;
  return true;
}
