"""Google Sheets Monitor integration."""
from __future__ import annotations

import json
import logging
from datetime import timedelta
from typing import Any

import gspread
from google.oauth2.service_account import Credentials

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .const import (
    CONF_CREDENTIALS_JSON,
    CONF_PERSON_NAME,
    CONF_SCAN_INTERVAL,
    CONF_SHEET_ID,
    CONF_SHEET_NAME,
    CONF_SHEETS,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    EVENT_ROW_CHANGE,
    GOOGLE_SCOPES,
)

_LOGGER = logging.getLogger(__name__)

STORAGE_VERSION = 1


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Google Sheets Monitor from a config entry."""
    hass.data.setdefault(DOMAIN, {})

    person_name = entry.data[CONF_PERSON_NAME]
    credentials_json = entry.data[CONF_CREDENTIALS_JSON]
    sheets = entry.data[CONF_SHEETS]

    # Parse and cache credentials once at setup — not on every poll
    try:
        creds_dict = json.loads(credentials_json)
        def _build_creds():
            return Credentials.from_service_account_info(creds_dict, scopes=GOOGLE_SCOPES)
        creds = await hass.async_add_executor_job(_build_creds)
    except (json.JSONDecodeError, ValueError, KeyError) as err:
        _LOGGER.error("Invalid credentials JSON for %s: %s", person_name, err)
        raise ConfigEntryNotReady(f"Invalid credentials: {err}") from err
    except Exception as err:
        _LOGGER.error("Failed to load credentials for %s: %s", person_name, err)
        raise ConfigEntryNotReady(f"Credentials error: {err}") from err

    # Persistent state storage using HA's Store helper
    store = Store(hass, STORAGE_VERSION, f"{DOMAIN}_{entry.entry_id}")
    sheet_states: dict[str, Any] = await store.async_load() or {}

    # Track interval cancel callbacks so we can clean up on unload
    cancel_callbacks = []

    async def fetch_spreadsheet(
        client: gspread.Client, spreadsheet_id: str, sheet_name: str | None
    ) -> tuple[gspread.Worksheet, list[dict]]:
        """Fetch spreadsheet data in a non-blocking way."""
        spreadsheet = await hass.async_add_executor_job(
            client.open_by_key, spreadsheet_id
        )
        if sheet_name:
            sheet = await hass.async_add_executor_job(
                spreadsheet.worksheet, sheet_name
            )
        else:
            sheet = await hass.async_add_executor_job(lambda: spreadsheet.sheet1)

        def _get_rows(ws: gspread.Worksheet) -> list[dict]:
            """Fetch all rows, tolerating empty/duplicate header columns.

            get_all_records() raises if any header cell is blank or duplicated
            (common when a sheet has empty trailing columns). We use
            get_all_values() instead and build the dicts ourselves, skipping
            columns whose header is empty and completely empty data rows.

            Each returned dict includes two reserved keys:
              _sheet_row   — 1-based spreadsheet row number (row 1 = header)
              _col_numbers — dict mapping header name -> 1-based column number
            These are stripped from event payloads before firing.
            """
            all_values = ws.get_all_values()
            if not all_values:
                return []
            headers = all_values[0]
            # Build a mapping of header name -> 1-based column number for
            # non-empty headers only, keeping the first occurrence if duplicated.
            col_numbers: dict[str, int] = {}
            for col_idx, h in enumerate(headers, start=1):
                if h.strip() and h not in col_numbers:
                    col_numbers[h] = col_idx
            rows = []
            # all_values[0] is the header row (sheet row 1), so data starts at
            # sheet row 2 — enumerate with start=2 to track the real row number.
            for sheet_row_number, row in enumerate(all_values[1:], start=2):
                # Pad short rows so zip doesn't truncate
                padded = row + [""] * (len(headers) - len(row))
                row_dict = {
                    h: v
                    for h, v in zip(headers, padded)
                    if h.strip()  # skip blank-header columns entirely
                }
                # Skip completely empty rows
                if any(v.strip() for v in row_dict.values()):
                    row_dict["_sheet_row"] = sheet_row_number
                    row_dict["_col_numbers"] = col_numbers
                    rows.append(row_dict)
            return rows

        data = await hass.async_add_executor_job(_get_rows, sheet)
        return sheet, data

    def make_check_sheet(
        entry_person_name: str,
        entry_creds: Credentials,
        entry_sheet_config: dict,
    ):
        """Return a bound check_sheet coroutine — fixes closure capture bug."""

        async def check_sheet(now) -> None:
            """Periodically check a Google Sheet for changes."""
            spreadsheet_id = entry_sheet_config[CONF_SHEET_ID]
            sheet_name = entry_sheet_config.get(CONF_SHEET_NAME)
            state_key = f"{entry_person_name}:{spreadsheet_id}"

            try:
                def _make_client():
                    return gspread.Client(auth=entry_creds)
                client = await hass.async_add_executor_job(_make_client)
                sheet, data = await fetch_spreadsheet(
                    client, spreadsheet_id, sheet_name
                )
            except gspread.exceptions.APIError as err:
                _LOGGER.warning(
                    "Google Sheets API error for %s / %s: %s",
                    entry_person_name,
                    spreadsheet_id,
                    err,
                )
                return
            except gspread.exceptions.SpreadsheetNotFound:
                _LOGGER.error(
                    "Spreadsheet %s not found or not shared with service account",
                    spreadsheet_id,
                )
                return
            except Exception as err:
                _LOGGER.error(
                    "Unexpected error monitoring sheet %s for %s: %s",
                    spreadsheet_id,
                    entry_person_name,
                    err,
                )
                return

            if state_key not in sheet_states:
                # First run — initialise state, no events fired
                _LOGGER.info(
                    "Initialising state for %s / %s (%d rows) — changes will be detected from next poll",
                    entry_person_name,
                    spreadsheet_id,
                    len(data),
                )
                sheet_states[state_key] = data
                await store.async_save(sheet_states)
                return

            last_data = sheet_states[state_key]
            fired_at = dt_util.now().isoformat()

            def _clean(row: dict) -> dict:
                """Strip internal tracking keys from row data before firing event."""
                return {k: v for k, v in row.items() if k not in ("_sheet_row", "_col_numbers")}

            # Changed or added rows
            for i, row in enumerate(data):
                sheet_row = row.get("_sheet_row", i + 2)
                clean_row = _clean(row)
                if i >= len(last_data):
                    _LOGGER.info(
                        "Row add detected: %s / %s row %d",
                        entry_person_name,
                        spreadsheet_id,
                        sheet_row,
                    )
                    hass.bus.fire(
                        EVENT_ROW_CHANGE,
                        {
                            "person": entry_person_name,
                            "spreadsheet_id": spreadsheet_id,
                            "sheet_name": sheet.title,
                            "event_type": "add",
                            "row_number": sheet_row,
                            "row_data": clean_row,
                            "fired_at": fired_at,
                        },
                    )
                elif _clean(row) != _clean(last_data[i]):
                    old_row = _clean(last_data[i])
                    col_numbers = row.get("_col_numbers", {})
                    changed_columns = [
                        k for k in set(list(clean_row.keys()) + list(old_row.keys()))
                        if clean_row.get(k) != old_row.get(k)
                    ]
                    changed_column_numbers = [
                        col_numbers[k] for k in changed_columns if k in col_numbers
                    ]
                    _LOGGER.info(
                        "Row change detected: %s / %s row %d (columns: %s)",
                        entry_person_name,
                        spreadsheet_id,
                        sheet_row,
                        ", ".join(changed_columns),
                    )
                    hass.bus.fire(
                        EVENT_ROW_CHANGE,
                        {
                            "person": entry_person_name,
                            "spreadsheet_id": spreadsheet_id,
                            "sheet_name": sheet.title,
                            "event_type": "change",
                            "row_number": sheet_row,
                            "row_data": clean_row,
                            "previous_row_data": old_row,
                            "changed_columns": changed_columns,
                            "changed_column_numbers": changed_column_numbers,
                            "fired_at": fired_at,
                        },
                    )

            # Deleted rows
            if len(data) < len(last_data):
                for i in range(len(data), len(last_data)):
                    deleted_row = last_data[i]
                    sheet_row = deleted_row.get("_sheet_row", i + 2)
                    _LOGGER.info(
                        "Row delete detected: %s / %s row %d",
                        entry_person_name,
                        spreadsheet_id,
                        sheet_row,
                    )
                    hass.bus.fire(
                        EVENT_ROW_CHANGE,
                        {
                            "person": entry_person_name,
                            "spreadsheet_id": spreadsheet_id,
                            "sheet_name": sheet.title,
                            "event_type": "delete",
                            "row_number": sheet_row,
                            "row_data": _clean(deleted_row),
                            "fired_at": fired_at,
                        },
                    )

            sheet_states[state_key] = data
            await store.async_save(sheet_states)

        return check_sheet

    # Register a polling interval for each sheet
    for sheet_config in sheets:
        interval = sheet_config.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
        check_fn = make_check_sheet(person_name, creds, sheet_config)

        # Run immediately on setup, then on interval
        await check_fn(None)

        cancel = async_track_time_interval(
            hass, check_fn, timedelta(seconds=interval)
        )
        cancel_callbacks.append(cancel)

    hass.data[DOMAIN][entry.entry_id] = {
        "cancel_callbacks": cancel_callbacks,
        "store": store,
    }

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry and cancel all polling intervals."""
    entry_data = hass.data[DOMAIN].pop(entry.entry_id, {})
    for cancel in entry_data.get("cancel_callbacks", []):
        cancel()
    return True
