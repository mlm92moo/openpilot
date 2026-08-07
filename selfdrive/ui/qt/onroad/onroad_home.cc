#include "selfdrive/ui/qt/onroad/onroad_home.h"

#include <cmath>
#include <QApplication>
#include <QPainter>
#include <QStackedLayout>
#include <QTimer>

#ifdef ENABLE_MAPS
#include "selfdrive/ui/qt/maps/map_helpers.h"
#include "selfdrive/ui/qt/maps/map_panel.h"
#endif

#include "selfdrive/ui/qt/util.h"

#include "frogpilot/ui/qt/onroad/personal_speed_zone_config.h"

OnroadWindow::OnroadWindow(QWidget *parent) : QWidget(parent) {
  QVBoxLayout *main_layout  = new QVBoxLayout(this);
  main_layout->setMargin(UI_BORDER_SIZE);
  QStackedLayout *stacked_layout = new QStackedLayout;
  stacked_layout->setStackingMode(QStackedLayout::StackAll);
  main_layout->addLayout(stacked_layout);

  nvg = new AnnotatedCameraWidget(VISION_STREAM_ROAD, this);

  QWidget * split_wrapper = new QWidget;
  split = new QHBoxLayout(split_wrapper);
  split->setContentsMargins(0, 0, 0, 0);
  split->setSpacing(0);
  split->addWidget(nvg);

  if (getenv("DUAL_CAMERA_VIEW")) {
    CameraWidget *arCam = new CameraWidget("camerad", VISION_STREAM_ROAD, true, this);
    split->insertWidget(0, arCam);
  }

  if (getenv("MAP_RENDER_VIEW")) {
    CameraWidget *map_render = new CameraWidget("navd", VISION_STREAM_MAP, false, this);
    split->insertWidget(0, map_render);
  }

  stacked_layout->addWidget(split_wrapper);

  alerts = new OnroadAlerts(this);
  alerts->setAttribute(Qt::WA_TransparentForMouseEvents, true);
  stacked_layout->addWidget(alerts);

  // setup stacking order
  alerts->raise();

  setAttribute(Qt::WA_OpaquePaintEvent);
  QObject::connect(uiState(), &UIState::uiUpdate, this, &OnroadWindow::updateState);
  QObject::connect(uiState(), &UIState::offroadTransition, this, &OnroadWindow::offroadTransition);
  QObject::connect(uiState(), &UIState::primeChanged, this, &OnroadWindow::primeChanged);

  // FrogPilot variables
  frogpilot_onroad = new FrogPilotOnroadWindow(this);
  frogpilot_onroad->setAttribute(Qt::WA_TransparentForMouseEvents, true);

  personal_speed_zone_button = new QPushButton(this);
  personal_speed_zone_button->setFocusPolicy(Qt::NoFocus);
  personal_speed_zone_button->setFixedSize(620, 160);
  personal_speed_zone_button->setStyleSheet(
    "QPushButton { background-color: rgba(23, 134, 68, 235); border: 8px solid white; "
    "border-radius: 32px; color: white; font-size: 43px; font-weight: 700; padding: 8px; } "
    "QPushButton:pressed { background-color: rgba(13, 94, 48, 245); }");
  personal_speed_zone_button->setText(tr("MARK SLOWDOWN"));
  personal_speed_zone_button->setVisible(false);
  QObject::connect(personal_speed_zone_button, &QPushButton::pressed, [this] {
    personal_speed_zone_press_timer.restart();
  });
  QObject::connect(personal_speed_zone_button, &QPushButton::released, this, &OnroadWindow::handlePersonalSpeedZoneRelease);
}

void OnroadWindow::resizeEvent(QResizeEvent *event) {
  QWidget::resizeEvent(event);

  frogpilot_onroad->setGeometry(rect());
  personal_speed_zone_button->move((width() - personal_speed_zone_button->width()) / 2,
                                   height() - personal_speed_zone_button->height() - UI_BORDER_SIZE * 2);
  personal_speed_zone_button->raise();
}

void OnroadWindow::updateState(const UIState &s, const FrogPilotUIState &fs) {
  if (!s.scene.started) {
    return;
  }

  if (s.scene.map_on_left) {
    split->setDirection(QBoxLayout::LeftToRight);
  } else {
    split->setDirection(QBoxLayout::RightToLeft);
  }

  alerts->updateState(s, fs);
  nvg->updateState(s, fs);

  QColor bgColor = bg_colors[s.status];
  if (bg != bgColor) {
    // repaint border
    bg = bgColor;
    update();
  }

  // FrogPilot variables
  frogpilot_onroad->bg = bg;
  frogpilot_onroad->fps = nvg->fps;

  nvg->frogpilot_nvg->alertHeight = alerts->alertHeight;

  frogpilot_onroad->updateState(s, fs);
  updatePersonalSpeedZoneRecorder(s);
}

void OnroadWindow::updatePersonalSpeedZoneRecorder(const UIState &s) {
  personal_speed_zone_position_valid = false;
  const SubMaster &sm = *(s.sm);
  if (sm.alive("liveLocationKalman")) {
    const auto location = sm["liveLocationKalman"].getLiveLocationKalman();
    const auto position = location.getPositionGeodetic();
    const auto orientation = location.getCalibratedOrientationNED();
    if (location.getGpsOK() && location.getStatus() == cereal::LiveLocationKalman::Status::VALID &&
        position.getValid() && orientation.getValid() && position.getValue().size() >= 2 && orientation.getValue().size() >= 3) {
      const double latitude = position.getValue()[0];
      const double longitude = position.getValue()[1];
      double bearing = std::fmod(orientation.getValue()[2] * 180.0 / M_PI + 360.0, 360.0);
      if (std::isfinite(latitude) && std::isfinite(longitude) && std::isfinite(bearing) &&
          latitude >= -90.0 && latitude <= 90.0 && longitude >= -180.0 && longitude <= 180.0) {
        personal_speed_zone_position = {{"latitude", latitude}, {"longitude", longitude}, {"bearing", bearing}};
        personal_speed_zone_position_valid = true;
      }
    }
  }

  personal_speed_zone_button->setVisible(!alerts->hasAlert());
  if (!alerts->hasAlert()) personal_speed_zone_button->raise();
}

void OnroadWindow::showPersonalSpeedZoneMessage(const QString &message, const QString &color, int duration_ms) {
  personal_speed_zone_message_visible = true;
  personal_speed_zone_button->setText(message);
  personal_speed_zone_button->setStyleSheet(QString(
    "QPushButton { background-color: %1; border: 8px solid white; border-radius: 32px; "
    "color: white; font-size: 43px; font-weight: 700; padding: 8px; }").arg(color));
  QTimer::singleShot(duration_ms, this, [this] {
    personal_speed_zone_message_visible = false;
    personal_speed_zone_button->setStyleSheet(
      "QPushButton { background-color: rgba(23, 134, 68, 235); border: 8px solid white; "
      "border-radius: 32px; color: white; font-size: 43px; font-weight: 700; padding: 8px; } "
      "QPushButton:pressed { background-color: rgba(13, 94, 48, 245); }");
    personal_speed_zone_button->setText(personal_speed_zone_start.isEmpty() ? tr("MARK SLOWDOWN") : tr("MARK RESUME\nHOLD TO CANCEL"));
    personal_speed_zone_button->setVisible(!alerts->hasAlert());
  });
}

void OnroadWindow::handlePersonalSpeedZoneRelease() {
  if (alerts->hasAlert() || !personal_speed_zone_button->isVisible() || personal_speed_zone_message_visible ||
      (personal_speed_zone_tap_timer.isValid() && personal_speed_zone_tap_timer.elapsed() < 1000)) {
    return;
  }
  personal_speed_zone_tap_timer.restart();

  if (!personal_speed_zone_start.isEmpty() && personal_speed_zone_press_timer.isValid() && personal_speed_zone_press_timer.elapsed() >= 1500) {
    personal_speed_zone_start = QJsonObject();
    QApplication::beep();
    showPersonalSpeedZoneMessage(tr("RECORDING CANCELED"), "rgba(218, 111, 37, 245)");
    return;
  }

  if (!personal_speed_zone_position_valid) {
    showPersonalSpeedZoneMessage(tr("GPS UNAVAILABLE"), "rgba(201, 34, 49, 245)");
    return;
  }

  if (personal_speed_zone_start.isEmpty()) {
    personal_speed_zone_start = personal_speed_zone_position;
    QApplication::beep();
    showPersonalSpeedZoneMessage(tr("START SAVED"), "rgba(23, 134, 68, 245)", 1200);
    return;
  }

  constexpr double earth_radius_m = 6371000.0;
  const double lat1 = personal_speed_zone_start["latitude"].toDouble() * M_PI / 180.0;
  const double lat2 = personal_speed_zone_position["latitude"].toDouble() * M_PI / 180.0;
  const double d_lat = lat2 - lat1;
  const double d_lon = (personal_speed_zone_position["longitude"].toDouble() - personal_speed_zone_start["longitude"].toDouble()) * M_PI / 180.0;
  const double a = std::sin(d_lat / 2.0) * std::sin(d_lat / 2.0) + std::cos(lat1) * std::cos(lat2) * std::sin(d_lon / 2.0) * std::sin(d_lon / 2.0);
  const double distance = earth_radius_m * 2.0 * std::atan2(std::sqrt(a), std::sqrt(1.0 - a));
  if (distance < 10.0) {
    showPersonalSpeedZoneMessage(tr("DRIVE FARTHER"), "rgba(218, 111, 37, 245)");
    return;
  }

  if (!appendPersonalSpeedZone("/data/personal_speed_zones.json", personal_speed_zone_start,
                               personal_speed_zone_position, params.getInt("PersonalSpeedZoneTarget"))) {
    showPersonalSpeedZoneMessage(tr("SAVE FAILED"), "rgba(201, 34, 49, 245)");
    return;
  }

  personal_speed_zone_start = QJsonObject();
  QApplication::beep();
  showPersonalSpeedZoneMessage(tr("ZONE SAVED - ACTIVE"), "rgba(49, 161, 238, 245)", 3000);
}

void OnroadWindow::mousePressEvent(QMouseEvent* e) {
  FrogPilotUIState &fs = *frogpilotUIState();
  QJsonObject &frogpilot_toggles = fs.frogpilot_toggles;
  SubMaster &fpsm = *(fs.sm);

  if (fpsm["frogpilotPlan"].getFrogpilotPlan().getSpeedLimitChanged() && nvg->frogpilot_nvg->newSpeedLimitRect.contains(e->pos())) {
    fs.params_memory.putBool("SpeedLimitAccepted", true);
    return;
  }

#ifdef ENABLE_MAPS
  if (map != nullptr) {
    bool sidebarVisible = geometry().x() > 0;
    bool show_map = !sidebarVisible && !frogpilot_toggles.value("hide_map").toBool();
    map->setVisible(show_map && !map->isVisible());
    if (map->isVisible() && frogpilot_toggles.value("full_map").toBool()) {
      nvg->frogpilot_nvg->bigMapOpen = false;

      map->setFixedSize(this->size());

      alerts->setVisible(false);
      nvg->setVisible(false);
    } else if (map->isVisible() && frogpilot_toggles.value("big_map").toBool()) {
      nvg->frogpilot_nvg->bigMapOpen = true;

      map->setFixedWidth(topWidget(this)->width() * 3 / 4 - UI_BORDER_SIZE);

      alerts->setVisible(true);
      nvg->setVisible(true);
    } else {
      nvg->frogpilot_nvg->bigMapOpen = false;

      map->setFixedWidth(topWidget(this)->width() / 2 - UI_BORDER_SIZE);

      alerts->setVisible(true);
      nvg->setVisible(true);
    }
    nvg->screen_recorder->setVisible(!map->isVisible() && frogpilot_toggles.value("screen_recorder").toBool());
  }
#endif
  // propagation event to parent(HomeWindow)
  QWidget::mousePressEvent(e);
}

void OnroadWindow::createMapWidget() {
  FrogPilotUIState &fs = *frogpilotUIState();
  QJsonObject &frogpilot_toggles = fs.frogpilot_toggles;

  if (frogpilot_toggles.value("hide_map").toBool()) {
    return;
  }

#ifdef ENABLE_MAPS
  auto m = new MapPanel(get_mapbox_settings());
  map = m;
  QObject::connect(m, &MapPanel::mapPanelRequested, this, &OnroadWindow::mapPanelRequested);
  QObject::connect(nvg->map_settings_btn, &MapSettingsButton::clicked, m, &MapPanel::toggleMapSettings);
  nvg->map_settings_btn->setEnabled(true);

  m->setFixedWidth(topWidget(this)->width() / 2 - UI_BORDER_SIZE);
  split->insertWidget(0, m);
  // hidden by default, made visible when navRoute is published
  m->setVisible(false);
#endif
}

void OnroadWindow::offroadTransition(bool offroad) {
#ifdef ENABLE_MAPS
  if (!offroad) {
    if (map == nullptr && !MAPBOX_TOKEN.isEmpty()) {
      createMapWidget();
    }
  }
#endif
  alerts->clear();
  if (!offroad) {
    alerts->enableFerg = util::random_int(0, 1) == 1;
  } else {
    alerts->displayFerg = false;
    personal_speed_zone_start = QJsonObject();
    personal_speed_zone_message_visible = false;
    personal_speed_zone_button->setText(tr("MARK SLOWDOWN"));
    personal_speed_zone_button->setVisible(false);
  }
}

void OnroadWindow::primeChanged(bool prime) {
#ifdef ENABLE_MAPS
  if (map && (!prime && MAPBOX_TOKEN.isEmpty())) {
    nvg->map_settings_btn->setEnabled(false);
    nvg->map_settings_btn->setVisible(false);
    map->deleteLater();
    map = nullptr;
  } else if (!map && (prime || !MAPBOX_TOKEN.isEmpty())) {
    createMapWidget();
  }
#endif
}

void OnroadWindow::paintEvent(QPaintEvent *event) {
  QPainter p(this);
  p.fillRect(rect(), QColor(bg.red(), bg.green(), bg.blue(), 255));
}
