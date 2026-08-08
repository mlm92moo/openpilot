#pragma once

#include <QJsonObject>
#include <QString>

bool appendPersonalSpeedZone(const QString &config_path, const QJsonObject &start, const QJsonObject &end,
                             int target_mph, QString *zone_id = nullptr);
bool clearPersonalSpeedZones(const QString &config_path);
int selectPersonalSpeedZoneTargetMph(int configured_target_mph, bool use_current_speed, double current_speed_mps);
