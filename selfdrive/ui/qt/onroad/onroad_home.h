#pragma once

#include <QElapsedTimer>
#include <QJsonObject>
#include <QLabel>
#include <QPushButton>

#include "selfdrive/ui/qt/onroad/alerts.h"
#include "selfdrive/ui/qt/onroad/annotated_camera.h"

#include "frogpilot/ui/qt/onroad/frogpilot_onroad.h"

class OnroadWindow : public QWidget {
  Q_OBJECT

public:
  OnroadWindow(QWidget* parent = 0);
  bool isMapVisible() const { return map && map->isVisible(); }
  void showMapPanel(bool show) { if (map) map->setVisible(show); }

signals:
  void mapPanelRequested();

private:
  void createMapWidget();
  void handlePersonalSpeedZoneRelease();
  void paintEvent(QPaintEvent *event);
  void mousePressEvent(QMouseEvent* e) override;
  void showPersonalSpeedZoneMessage(const QString &message, const QString &color, int duration_ms = 2000);
  void updatePersonalSpeedZoneRecorder(const UIState &s, const FrogPilotUIState &fs);
  OnroadAlerts *alerts;
  AnnotatedCameraWidget *nvg;
  QColor bg = bg_colors[STATUS_DISENGAGED];
  QWidget *map = nullptr;
  QHBoxLayout* split;

  // FrogPilot variables
  void resizeEvent(QResizeEvent *event);

  FrogPilotOnroadWindow *frogpilot_onroad;

  Params params;
  QPushButton *personal_speed_zone_button;
  QLabel *personal_speed_zone_status;
  bool personal_speed_zone_button_enabled = true;
  bool personal_speed_zone_current_speed_valid = false;
  bool personal_speed_zone_metric = false;
  QElapsedTimer personal_speed_zone_press_timer;
  QElapsedTimer personal_speed_zone_param_timer;
  QElapsedTimer personal_speed_zone_recording_timer;
  QElapsedTimer personal_speed_zone_tap_timer;
  QJsonObject personal_speed_zone_press_position;
  QJsonObject personal_speed_zone_start;
  QJsonObject personal_speed_zone_position;
  bool personal_speed_zone_message_visible = false;
  bool personal_speed_zone_onroad = false;
  bool personal_speed_zone_press_position_valid = false;
  bool personal_speed_zone_press_speed_valid = false;
  bool personal_speed_zone_position_valid = false;
  bool personal_speed_zone_recording_uses_current_speed = false;
  double personal_speed_zone_current_speed_mps = 0.0;
  double personal_speed_zone_min_speed_mps = 0.0;
  double personal_speed_zone_press_speed_mps = 0.0;
  int personal_speed_zone_recording_target_mph = 25;

private slots:
  void offroadTransition(bool offroad);
  void primeChanged(bool prime);
  void updateState(const UIState &s, const FrogPilotUIState &fs);
};
