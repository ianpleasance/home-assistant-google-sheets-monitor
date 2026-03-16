# Google Sheets Monitor

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://github.com/custom-components/hacs)
[![Version](https://img.shields.io/badge/version-1.4.2-blue.svg)](https://github.com/ianpleasance/home-assistant-google-sheets-monitor)

A Home Assistant custom integration that monitors Google Sheets for row changes, additions, and deletions, and fires events that can trigger automations.

---

## Features

- Monitor multiple Google Sheets for row-level changes, additions, and deletions
- Configure via the Home Assistant UI — no `configuration.yaml` editing required
- Credentials stored securely in Home Assistant's encrypted config store — no JSON files on disk
- Supports multiple independent monitors (one config entry per person / use case)
- Configurable scan interval per sheet (10–3600 seconds, default: 30)
- Optional subsheet (tab) targeting — defaults to the first sheet if not specified
- Fires a `google_sheets_row_change` event with full row data, previous row data, changed column names and numbers, and a timestamp for easy automation
- Tolerates sheets with blank or trailing empty columns
- All 13 languages supported: Danish, Dutch, English, Finnish, French, German, Italian, Japanese, Norwegian, Polish, Portuguese, Spanish, Swedish

---

## Requirements

1. A Google Cloud project with the **Google Sheets API** enabled
2. A **Service Account** with a downloaded JSON key file
3. The Google Sheet must be shared with the service account's `client_email` (Viewer access is sufficient)
4. Home Assistant 2024.1.0 or newer

---

## Installation

### Via HACS (recommended)

1. Open HACS in Home Assistant
2. Go to **Integrations** → **⋮** → **Custom repositories**
3. Add `https://github.com/ianpleasance/home-assistant-google-sheets-monitor` as category **Integration**
4. Search for **Google Sheets Monitor** and install it
5. Restart Home Assistant
6. Go to **Settings → Devices & Services → Add Integration**, search for **Google Sheets Monitor** and follow the configuration steps

### Manual

1. Download the latest release from the [GitHub releases page](https://github.com/ianpleasance/home-assistant-google-sheets-monitor/releases)
2. Extract the archive and copy the `google_sheets_monitor` folder into your `<config>/custom_components/` directory so the path is `<config>/custom_components/google_sheets_monitor/`
3. Restart Home Assistant
4. Go to **Settings → Devices & Services → Add Integration**, search for **Google Sheets Monitor** and follow the configuration steps

---

## Google Cloud Setup

### 1. Enable the Google Sheets API

1. Go to the [Google Cloud Console](https://console.cloud.google.com/)
2. Create a new project or select an existing one
3. Navigate to **APIs & Services → Library**
4. Search for **Google Sheets API** and enable it

> The Google Drive API is **not** required.

### 2. Create a Service Account

1. Go to **APIs & Services → Credentials**
2. Click **Create Credentials → Service Account**
3. Give it a name (e.g. `home-assistant-sheets`) and click **Create and Continue**
4. No additional roles are required — click **Done**
5. Click the service account you just created to open it
6. Go to the **Keys** tab → **Add Key → Create new key → JSON**
7. The JSON key file will download automatically — keep it safe, you will paste its contents into Home Assistant during setup

### 3. Share Your Spreadsheet

1. Open the Google Sheet you want to monitor in your browser
2. Click **Share**
3. Enter the `client_email` from the downloaded JSON file (e.g. `my-monitor@my-project.iam.gserviceaccount.com`)
4. Set access to **Viewer** and click **Share**

> If the sheet is not shared with the service account, the integration will log a `SpreadsheetNotFound` error and will not monitor the sheet.

---

## Configuration

1. In Home Assistant go to **Settings → Devices & Services → Add Integration**
2. Search for **Google Sheets Monitor**
3. Enter a **Monitor Name** (any label, e.g. `Alice` or `Sales Tracker`) — this appears in event data to identify which monitor fired the event
4. Open your downloaded JSON key file in a text editor, select all, and paste the full contents into the **Service Account Credentials** field
5. Click **Submit**
6. Enter the **Spreadsheet ID** — this is the long string in the spreadsheet URL: `docs.google.com/spreadsheets/d/{SPREADSHEET_ID}/edit`
7. Optionally enter a **Sheet Name** (the tab name at the bottom of the sheet) — leave blank to monitor the first tab
8. Set a **Scan Interval** in seconds (default: 30, minimum: 10)
9. Choose whether to add more sheets to this monitor, then click **Submit** to finish

To monitor sheets with different credentials (e.g. for a different Google account or project), add a second integration instance via **Add Integration** again.

---

## Events

When a change is detected the integration fires a `google_sheets_row_change` event. The payload fields are:

| Field | Event types | Description |
|---|---|---|
| `person` | all | The monitor name set during configuration |
| `spreadsheet_id` | all | The ID of the monitored spreadsheet |
| `sheet_name` | all | The name of the monitored tab |
| `event_type` | all | `add`, `change`, or `delete` |
| `row_number` | all | The actual 1-based row number in the spreadsheet (row 1 is the header, so data begins at row 2) |
| `row_data` | all | Current row contents as a dict keyed by column header; for `delete` events this contains the row as it was before deletion |
| `previous_row_data` | `change` only | The row contents before the change was made |
| `changed_columns` | `change` only | List of column header names whose value changed, e.g. `["Status", "Notes"]` |
| `changed_column_numbers` | `change` only | List of 1-based column numbers corresponding to `changed_columns`, e.g. `[3, 5]` |
| `fired_at` | all | ISO 8601 timestamp of when the event was fired |

### Row data format

Row data is a dictionary using the spreadsheet's header row as keys. For example, a sheet with columns **Branch** and **City** produces:

```json
{"Branch": "Southern", "City": "London"}
```

Columns with blank headers are excluded. Completely empty rows are skipped and do not appear in change detection.

---

## Example Automation

The following automation notifies a mobile device when any row changes, showing which columns changed with before and after values:

```yaml
- alias: "Google Sheets Row Change Notification"
  id: google_sheets_change
  description: "Notify when a Google Sheet row is added, changed or deleted"
  mode: queued
  max: 10
  trigger:
    - platform: event
      event_type: google_sheets_row_change
  action:
    - variables:
        event_type: "{{ trigger.event.data.event_type }}"
        person: "{{ trigger.event.data.person }}"
        sheet_name: "{{ trigger.event.data.sheet_name }}"
        row_number: "{{ trigger.event.data.row_number }}"
        spreadsheet_id: "{{ trigger.event.data.spreadsheet_id }}"
    - service: notify.mobile_app_my_phone
      data:
        title: >-
          {% if event_type == 'add' %}[+]
          {% elif event_type == 'change' %}[~]
          {% elif event_type == 'delete' %}[-]
          {% endif -%}
          {{ sheet_name }} — Row {{ row_number }} {{ event_type }}d
        message: >-
          {% set row = trigger.event.data.row_data %}
          {% set prev = trigger.event.data.previous_row_data | default({}) %}
          {% set changed = trigger.event.data.changed_columns | default([]) %}
          {% set parts = namespace(items=[]) %}
          {% for key, value in row.items() %}
            {% if key in changed %}
              {% set parts.items = parts.items + [key ~ ': ' ~ prev.get(key, '?') ~ ' -> ' ~ value] %}
            {% else %}
              {% set parts.items = parts.items + [key ~ ': ' ~ value] %}
            {% endif %}
          {% endfor %}
          {{ parts.items | join('\n') }}
        data:
          tag: "sheets_{{ spreadsheet_id }}_row_{{ row_number }}"
          group: google_sheets
          clickAction: "https://docs.google.com/spreadsheets/d/{{ spreadsheet_id }}/edit"
```

You can narrow the trigger or add conditions to handle specific sheets, monitors, or change types:

```yaml
# Only fire for a specific spreadsheet
condition:
  - condition: template
    value_template: "{{ trigger.event.data.spreadsheet_id == 'YOUR_SPREADSHEET_ID' }}"

# Only fire for a specific monitor
condition:
  - condition: template
    value_template: "{{ trigger.event.data.person == 'Sales Tracker' }}"

# Only fire for additions
condition:
  - condition: template
    value_template: "{{ trigger.event.data.event_type == 'add' }}"

# Only fire when a specific column changes (by name)
condition:
  - condition: template
    value_template: "{{ 'Status' in trigger.event.data.changed_columns | default([]) }}"

# Only fire when a specific column changes (by number)
condition:
  - condition: template
    value_template: "{{ 3 in trigger.event.data.changed_column_numbers | default([]) }}"
```

---

## Notes

- The first poll after setup or restart initialises the baseline state — no events are fired on that first run. Changes made before the second poll will be detected normally
- State is persisted across Home Assistant restarts using HA's internal storage (`.storage/google_sheets_monitor_*`)
- Google rate-limits the Sheets API. Setting a very low scan interval across many sheets may result in HTTP 429 errors — if this happens, increase the scan interval
- The monitor name does not need to match a Home Assistant user or person entity

---

## Upgrading from v1.2

Version 1.3.0 replaced the legacy `configuration.yaml` setup with a UI config flow. If upgrading from v1.2:

1. Remove the `google_sheets_monitor:` block from your `configuration.yaml`
2. Restart Home Assistant
3. Go to **Settings → Devices & Services → Add Integration** and configure via the UI
4. Your service account JSON file is no longer needed on disk — paste its contents into the UI and it will be stored securely by Home Assistant

---

## Version History

| Version | Changes |
|---|---|
| 1.4.2 | `change` events now include `previous_row_data`, `changed_columns` (list of header names), and `changed_column_numbers` (list of 1-based column numbers); fixed row number reporting to reflect the actual spreadsheet row rather than the filtered list position; fixed handling of sheets with blank or duplicate header columns |
| 1.3.0 | Full config flow UI setup; credentials stored in HA secure storage; fixed closure bug causing all sheets to poll only the last configured sheet; API scope narrowed to `spreadsheets.readonly`; state persistence migrated to HA `Store` helper; credentials cached at setup; clean unload/reload support; `fired_at` timestamp added to events; 13-language translation support; HACS support |
| 1.2.0 | `configuration.yaml`-based setup |

---

## License

Apache License 2.0 — see [LICENSE](LICENSE)
