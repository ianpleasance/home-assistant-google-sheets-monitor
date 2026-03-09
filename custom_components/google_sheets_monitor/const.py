"""Constants for the Google Sheets Monitor integration."""
from __future__ import annotations

DOMAIN = "google_sheets_monitor"

# Config entry keys
CONF_CREDENTIALS_JSON = "credentials_json"
CONF_SHEETS = "sheets"
CONF_SHEET_ID = "id"
CONF_SHEET_NAME = "name"
CONF_SCAN_INTERVAL = "scan_interval"
CONF_PERSON_NAME = "person_name"

# Defaults
DEFAULT_SCAN_INTERVAL = 30  # seconds

# Google API scope — readonly, principle of least privilege
GOOGLE_SCOPES = ["https://www.googleapis.com/auth/spreadsheets.readonly"]

# Event name fired on sheet changes
EVENT_ROW_CHANGE = "google_sheets_row_change"
