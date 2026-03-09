"""Config flow for Google Sheets Monitor."""
from __future__ import annotations

import json
import logging
from typing import Any

import gspread
from google.oauth2.service_account import Credentials
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import HomeAssistant, callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers import selector

from .const import (
    CONF_CREDENTIALS_JSON,
    CONF_PERSON_NAME,
    CONF_SCAN_INTERVAL,
    CONF_SHEET_ID,
    CONF_SHEET_NAME,
    CONF_SHEETS,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    GOOGLE_SCOPES,
)

_LOGGER = logging.getLogger(__name__)


async def validate_credentials(hass: HomeAssistant, credentials_json: str) -> dict:
    """Parse and validate service account credentials JSON.

    Returns the parsed dict on success, raises ValueError on failure.
    """
    try:
        creds_dict = json.loads(credentials_json)
    except json.JSONDecodeError as err:
        raise ValueError("invalid_json") from err

    required_keys = {"type", "project_id", "private_key", "client_email"}
    if not required_keys.issubset(creds_dict.keys()):
        raise ValueError("missing_fields")

    if creds_dict.get("type") != "service_account":
        raise ValueError("not_service_account")

    # Attempt to actually authenticate against the API
    try:
        raw_creds = await hass.async_add_executor_job(
            Credentials.from_service_account_info, creds_dict
        )
        creds = raw_creds.with_scopes(GOOGLE_SCOPES)
        client = await hass.async_add_executor_job(gspread.authorize, creds)
        # List spreadsheets to verify connectivity (lightweight call)
        await hass.async_add_executor_job(client.list_spreadsheet_files)
    except Exception as err:
        _LOGGER.debug("Credential validation failed: %s", err)
        raise ValueError("cannot_connect") from err

    return creds_dict


STEP_USER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_PERSON_NAME): str,
        vol.Required(CONF_CREDENTIALS_JSON): selector.selector(
            {"text": {"multiline": True}}
        ),
    }
)

STEP_SHEET_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_SHEET_ID): str,
        vol.Optional(CONF_SHEET_NAME, default=""): str,
        vol.Optional(CONF_SCAN_INTERVAL, default=DEFAULT_SCAN_INTERVAL): vol.All(
            vol.Coerce(int), vol.Range(min=10, max=3600)
        ),
    }
)


class GoogleSheetsMonitorConfigFlow(
    config_entries.ConfigFlow, domain=DOMAIN
):
    """Handle a config flow for Google Sheets Monitor."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialise the flow."""
        self._person_name: str = ""
        self._credentials_json: str = ""
        self._sheets: list[dict] = []

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the credentials step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            person_name = user_input[CONF_PERSON_NAME].strip()
            credentials_json = user_input[CONF_CREDENTIALS_JSON].strip()

            if not person_name:
                errors[CONF_PERSON_NAME] = "name_required"
            else:
                try:
                    await validate_credentials(self.hass, credentials_json)
                    self._person_name = person_name
                    self._credentials_json = credentials_json
                    return await self.async_step_sheet()
                except ValueError as err:
                    errors["base"] = str(err)
                except Exception:
                    errors["base"] = "unknown"

        return self.async_show_form(
            step_id="user",
            data_schema=STEP_USER_SCHEMA,
            errors=errors,
        )

    async def async_step_sheet(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle adding a sheet to monitor."""
        errors: dict[str, str] = {}

        if user_input is not None:
            sheet_id = user_input[CONF_SHEET_ID].strip()
            sheet_name = user_input.get(CONF_SHEET_NAME, "").strip() or None
            scan_interval = user_input.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)

            if not sheet_id:
                errors[CONF_SHEET_ID] = "sheet_id_required"
            else:
                self._sheets.append(
                    {
                        CONF_SHEET_ID: sheet_id,
                        CONF_SHEET_NAME: sheet_name,
                        CONF_SCAN_INTERVAL: scan_interval,
                    }
                )
                # Ask if they want to add another sheet
                return await self.async_step_add_another()

        return self.async_show_form(
            step_id="sheet",
            data_schema=STEP_SHEET_SCHEMA,
            errors=errors,
            description_placeholders={
                "person_name": self._person_name,
                "sheet_count": str(len(self._sheets)),
            },
        )

    async def async_step_add_another(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Ask whether to add another sheet or finish."""
        if user_input is not None:
            if user_input.get("add_another"):
                return await self.async_step_sheet()
            return self._create_entry()

        return self.async_show_form(
            step_id="add_another",
            data_schema=vol.Schema(
                {vol.Required("add_another", default=False): bool}
            ),
            description_placeholders={
                "sheet_count": str(len(self._sheets)),
                "person_name": self._person_name,
            },
        )

    def _create_entry(self) -> FlowResult:
        """Create the config entry."""
        return self.async_create_entry(
            title=f"Google Sheets — {self._person_name}",
            data={
                CONF_PERSON_NAME: self._person_name,
                CONF_CREDENTIALS_JSON: self._credentials_json,
                CONF_SHEETS: self._sheets,
            },
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: config_entries.ConfigEntry):
        """Return the options flow."""
        return GoogleSheetsMonitorOptionsFlow(config_entry)


class GoogleSheetsMonitorOptionsFlow(config_entries.OptionsFlow):
    """Handle options for Google Sheets Monitor."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        """Initialise options flow."""
        self.config_entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Manage options — currently just scan interval per sheet."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        sheets = self.config_entry.data.get(CONF_SHEETS, [])
        schema_dict = {}
        for i, sheet in enumerate(sheets):
            key = f"sheet_{i}_interval"
            schema_dict[
                vol.Optional(
                    key,
                    default=sheet.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
                )
            ] = vol.All(vol.Coerce(int), vol.Range(min=10, max=3600))

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(schema_dict),
        )
