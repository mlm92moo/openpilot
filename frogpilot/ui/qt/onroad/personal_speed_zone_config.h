#pragma once

#include <QJsonObject>
#include <QString>

bool appendPersonalSpeedZone(const QString &config_path, const QJsonObject &start, const QJsonObject &end,
                             int target_mph, QString *zone_id = nullptr);
