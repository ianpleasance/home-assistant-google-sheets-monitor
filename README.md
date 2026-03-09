# Google Sheets Monitor

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://github.com/custom-components/hacs)
[![Version](https://img.shields.io/badge/version-1.3.0-blue.svg)](https://github.com/ianpleasance/home-assistant-google-sheets-monitor)

A Home Assistant custom integration that monitors Google Sheets for row changes, additions, and deletions, and fires events that can trigger automations.

---

## Features

- Monitor multiple Google Sheets for row-level changes, additions, and deletions
- Configure via the Home Assistant UI — no `configuration.yaml` editing required
- Credentials stored securely in Home Assistant's encrypted config store — no JSON files on disk
- Supports multiple independent monitors (one config entry per person / use case)
- Configurable scan interval per sheet (10–3600 seconds, default: 30)
- Optional subsheet (tab) targeting — defaults to the first sheet if not specified
- Fires a `google_sheets_row_change` event with full row data and a timestamp for easy automation
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

### Manual

1. Copy the `google_sheets_monitor` folder to your `<config>/custom_components/` directory
2. Restart Home Assistant

---

## Google Cloud Setup

### 1. Enable the Google Sheets API

1. Go to the [Google Cloud Console](https://console.cloud.google.com/)
2. Create a new project or select an existing one
3. Navigate to **APIs & Services → Library**
4. Search for **Google Sheets API** and enable it

### 2. Create a Service Account

1. Go to **APIs & Services → Credentials**
2. Click **Create Credentials → Service Account**
3. Give it a name and click **Create and Continue**
4. No additional roles are required — click **Done**
5. Click the service account you just created
6. Go to the **Keys** tab → **Add Key → Create new key → JSON**
7. The JSON key file will be downloaded automatically

### 3. Share Your Spreadsheet

1. Open the Google Sheet you want to monitor
2. Click **Share**
3. Enter the `client_email` from the downloaded JSON file (e.g. `my-monitor@my-project.iam.gserviceaccount.com`)
4. Set access to **Viewer** and click **Share**

---

## Configuration

1. In Home Assistant go to **Settings → Devices & Services → Add Integration**
2. Search for **Google Sheets Monitor**
3. Enter a **Monitor Name** (any label, e.g. `Alice` or `Sales Tracker`) — this appears in event data
4. Open your downloaded JSON key file in a text editor, select all, and paste the contents into the **Service Account Credentials** field
5. Click **Submit** — the integration will validate the credentials by connecting to Google
6. Enter the **Spreadsheet ID** (from the spreadsheet URL: `docs.google.com/spreadsheets/d/{SPREADSHEET_ID}/edit`)
7. Optionally enter a **Sheet Name** (the tab name) — leave blank to monitor the first sheet
8. Set a **Scan Interval** in seconds (default: 30)
9. Choose whether to add more sheets for this monitor, then click **Submit** to finish

To monitor sheets for a different person or with different credentials, add a second integration instance via **Add Integration** again.

---

## Events

When a change is detected, the integration fires a `google_sheets_row_change` event with the following payload:

| Field | Description |
|---|---|
| `person` | The monitor name set during configuration |
| `spreadsheet_id` | The ID of the monitored spreadsheet |
| `sheet_name` | The name of the monitored tab |
| `event_type` | The type of change: `add`, `delete`, or `change` |
| `row_number` | The 1-based row number where the change occurred |
| `row_data` | The row contents as a dict keyed by column header (for `add` and `change` events); the previous contents for `delete` events |
| `fired_at` | ISO 8601 timestamp of when the event was fired |

### Row data format

Row data is a dictionary using the spreadsheet's header row as keys. For example, a sheet with columns **Branch** and **City** and values **Southern** and **London** produces:

```json
{"Branch": "Southern", "City": "London"}
```

---

## Example Automation

```yaml
automation:
  - alias: "Google Sheets Change Alert"
    trigger:
      platform: event
      event_type: google_sheets_row_change
    condition:
      - condition: template
        value_template: "{{ trigger.event.data.event_type == 'add' }}"
    action:
      - service: notify.mobile_app_my_phone
        data:
          title: "Spreadsheet updated"
          message: >
            New row added by {{ trigger.event.data.person }}
            in {{ trigger.event.data.sheet_name }}:
            {{ trigger.event.data.row_data }}
```

You can filter by `person`, `spreadsheet_id`, or `event_type` in the trigger or condition to handle specific sheets or change types differently.

---

## Notes

- The first poll after setup or restart initialises the baseline state — no events are fired on that first run
- State is persisted across Home Assistant restarts using HA's internal storage (`.storage/google_sheets_monitor_*`)
- Google rate-limits Sheets API calls. Setting a very low scan interval across many sheets may result in HTTP 429 errors. If this happens, increase the interval and restart Home Assistant
- Sheet headers must be unique — duplicate column names will cause `gspread` to raise an error
- The monitor name does not need to match a Home Assistant user or person entity

---

## Upgrading from v1.2

Version 1.3.0 replaces the legacy `configuration.yaml` setup with a UI config flow. After upgrading:

1. Remove the `google_sheets_monitor:` block from your `configuration.yaml`
2. Restart Home Assistant
3. Go to **Settings → Devices & Services → Add Integration** and configure via the UI
4. Your service account JSON file is no longer needed on disk — paste its contents into the UI and it will be stored securely by Home Assistant

---

## Version History

| Version | Changes |
|---|---|
| 1.3.0 | Full config flow UI setup; credentials stored in HA secure storage (no JSON file on disk); fixed closure bug causing all sheets to poll only the last configured sheet; API scope narrowed to `spreadsheets.readonly`; state persistence migrated to HA `Store` helper; credentials cached at setup (not reloaded every poll); clean unload/reload support; `fired_at` timestamp added to events; structured error handling per exception type; 13-language translation support; HACS support |
| 1.2.0 | `configuration.yaml`-based setup |

---

## License

MIT License — see [LICENSE](LICENSE)
