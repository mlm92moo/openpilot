"""Backward-compatible portal-settings imports.

The implementation lives with the daemon reader so both users share migration,
validation, locking, and revision behavior.
"""
from openpilot.custom.speed_limit.settings import (  # noqa: F401
  BOOLEAN_SETTINGS, PERSONALITIES, PERSONALITY_SETTINGS, PORTAL_SETTINGS,
  SIGN_OFFSET_SETTINGS, SPEED_LIMIT_SETTINGS, SettingsConflict, apply_settings,
  read_settings, settings_revision,
)
