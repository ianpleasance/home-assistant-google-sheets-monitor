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
        raw_creds = await hass.async_add_executor_job(
            Credentials.from_service_account_info, creds_dict
        )
        creds = raw_creds.with_scopes(GOOGLE_SCOPES)
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
        data = await hass.async_add_executor_job(sheet.get_all_records)
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
                client = await hass.async_add_executor_job(
                    gspread.authorize, entry_creds
                )
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
                _LOGGER.debug(
                    "Initialising state for %s / %s (%d rows)",
                    entry_person_name,
                    spreadsheet_id,
                    len(data),
                )
                sheet_states[state_key] = data
                await store.async_save(sheet_states)
                return

            last_data = sheet_states[state_key]
            fired_at = dt_util.now().isoformat()

            # Changed or added rows
            for i, row in enumerate(data):
                if i >= len(last_data):
                    _LOGGER.debug(
                        "Row add detected: %s / %s row %d",
                        entry_person_name,
                        spreadsheet_id,
                        i + 1,
                    )
                    hass.bus.fire(
                        EVENT_ROW_CHANGE,
                        {
                            "person": entry_person_name,
                            "spreadsheet_id": spreadsheet_id,
                            "sheet_name": sheet.title,
                            "event_type": "add",
                            "row_number": i + 1,
                            "row_data": row,
                            "fired_at": fired_at,
                        },
                    )
                elif row != last_data[i]:
                    _LOGGER.debug(
                        "Row change detected: %s / %s row %d",
                        entry_person_name,
                        spreadsheet_id,
                        i + 1,
                    )
                    hass.bus.fire(
                        EVENT_ROW_CHANGE,
                        {
                            "person": entry_person_name,
                            "spreadsheet_id": spreadsheet_id,
                            "sheet_name": sheet.title,
                            "event_type": "change",
                            "row_number": i + 1,
                            "row_data": row,
                            "fired_at": fired_at,
                        },
                    )

            # Deleted rows
            if len(data) < len(last_data):
                for i in range(len(data), len(last_data)):
                    _LOGGER.debug(
                        "Row delete detected: %s / %s row %d",
                        entry_person_name,
                        spreadsheet_id,
                        i + 1,
                    )
                    hass.bus.fire(
                        EVENT_ROW_CHANGE,
                        {
                            "person": entry_person_name,
                            "spreadsheet_id": spreadsheet_id,
                            "sheet_name": sheet.title,
                            "event_type": "delete",
                            "row_number": i + 1,
                            "row_data": last_data[i],
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
