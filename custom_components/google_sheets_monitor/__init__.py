from homeassistant.helpers.event import async_track_time_interval
from datetime import timedelta
import gspread
import aiofiles
import json
import logging
from google.oauth2.service_account import Credentials

DOMAIN = "google_sheets_monitor"
STATE_STORAGE_FILE = "google_sheets_states.json"
DEBUG = False

_LOGGER = logging.getLogger(__name__)

async def async_setup(hass, config):
    """Set up the Google Sheets Monitor integration."""
    people_config = config[DOMAIN].get("people", [])

    # Load previous states from file asynchronously
    async def load_states():
        try:
            async with aiofiles.open(hass.config.path(STATE_STORAGE_FILE), "r") as file:
                return json.loads(await file.read())
        except FileNotFoundError:
            return {}

    # Save states to file asynchronously
    async def save_states():
        async with aiofiles.open(hass.config.path(STATE_STORAGE_FILE), "w") as file:
            await file.write(json.dumps(sheet_states))

    # Initialize the states
    sheet_states = await load_states()

    async def fetch_spreadsheet(client, spreadsheet_id, sheet_name=None):
        """Fetch spreadsheet data in a non-blocking way."""
        spreadsheet = await hass.async_add_executor_job(client.open_by_key, spreadsheet_id)
        sheet = (
            await hass.async_add_executor_job(spreadsheet.worksheet, sheet_name)
            if sheet_name
            else await hass.async_add_executor_job(lambda: spreadsheet.sheet1)
        )
        data = await hass.async_add_executor_job(sheet.get_all_records)
        return sheet, data

    async def check_sheet(now, person_name, creds_file, sheet_config):
        """Periodically checks the Google Sheet for changes."""
        try:
            raw_creds = await hass.async_add_executor_job(
                Credentials.from_service_account_file,
                hass.config.path(creds_file),
            )
            creds = raw_creds.with_scopes(["https://www.googleapis.com/auth/spreadsheets"])
            client = gspread.authorize(creds)

            spreadsheet_id = sheet_config["id"]
            sheet_name = sheet_config.get("name", None)

            if DEBUG:
                _LOGGER.info(f"Monitoring sheet {spreadsheet_id} for {person_name}: {sheet_name}")           

            # Fetch spreadsheet data
            sheet, data = await fetch_spreadsheet(client, spreadsheet_id, sheet_name)

            # Unique key to store state
            state_key = f"{person_name}:{spreadsheet_id}"

            if state_key not in sheet_states:
                # First-time initialization
                sheet_states[state_key] = data
                await save_states()
                return

            last_data = sheet_states[state_key]
 
            if DEBUG:
                json_printable = json.dumps(last_data)
                _LOGGER.info(f"Latest data = {json_printable}")

            # Detect changes, additions, and deletions
            for i, row in enumerate(data):
                if i >= len(last_data) or row != last_data[i]:
                    if DEBUG:
                        _LOGGER.error("Firing row change")
                    hass.bus.fire(
                        "google_sheets_row_change",
                        {
                            "person": person_name,
                            "spreadsheet_id": spreadsheet_id,
                            "sheet_name": sheet.title,
                            "event_type": "change",
                            "row_number": i + 1,
                            "row_data": row,
                        },
                    )

            if len(data) > len(last_data):
                for i in range(len(last_data), len(data)):
                    if DEBUG:
                        _LOGGER.error("Firing row add")
                    hass.bus.fire(
                        "google_sheets_row_change",
                        {
                            "person": person_name,
                            "spreadsheet_id": spreadsheet_id,
                            "sheet_name": sheet.title,
                            "event_type": "add",
                            "row_number": i + 1,
                            "row_data": data[i],
                        },
                    )

            if len(data) < len(last_data):
                for i in range(len(data), len(last_data)):
                    if DEBUG:
                        _LOGGER.error("Firing row delete")
                    hass.bus.fire(
                        "google_sheets_row_change",
                        {
                            "person": person_name,
                            "spreadsheet_id": spreadsheet_id,
                            "sheet_name": sheet.title,
                            "event_type": "delete",
                            "row_number": i + 1,
                            "row_data": last_data[i],
                        },
                    )

            # Update state and save
            sheet_states[state_key] = data
            await save_states()

        except Exception as e:
            _LOGGER.error(f"Error monitoring sheet {spreadsheet_id} for {person_name}: {e}")

    # Schedule checks for each person and their sheets
    for person in people_config:
        person_name = person["name"]
        creds_file = person["credentials_file"]
        sheets = person.get("sheets", [])

        for sheet_config in sheets:
            interval = sheet_config.get("scan_interval", 30)

            async def periodic_check(now):
                await check_sheet(now, person_name, creds_file, sheet_config)

            async_track_time_interval(hass, periodic_check, timedelta(seconds=interval))

    return True

