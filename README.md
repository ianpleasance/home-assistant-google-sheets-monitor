
# Google Sheets Monitor

A Home Assistant custom integration to monitor changes in Google Sheets and trigger automations. This component allows you to detect when rows are added, deleted, or changed in specified Google Sheets and perform actions accordingly.

---

## Features

- Monitor multiple Google Sheets for changes, additions, or deletions.
- Supports individual configurations for different users, including:
  - Separate credentials for each user.
  - Per-sheet monitoring with optional subsheet names.
  - Configurable scan intervals (default: 30 seconds).
- Sends detailed events to Home Assistant for automation.

---

## Requirements

1. A Google Cloud project with the **Google Sheets API** enabled.
2. A service account credentials file for each user.
3. Google Sheets must:
   - Have a **header row** as the first row.
   - Be shared with the email address specified in the `client_email` field of the service account credentials file (with **Viewer** access or higher).

---

## Installation

### 1. Enable Google Sheets API
1. Go to the [Google Cloud Console](https://console.cloud.google.com/).
2. Create a new project or select an existing project.
3. Enable the **Google Sheets API** for the project.
4. Create a **Service Account** under **APIs & Services > Credentials**.
5. Download the service account credentials JSON file.

### 2. Share the Spreadsheet
1. Open the Google Sheet to monitor.
2. Click **Share** in the top-right corner.
3. Enter the email address from the `client_email` field in the credentials file (e.g., `service-account@your-project.iam.gserviceaccount.com`).
4. Set access to **Viewer** (or higher) and click **Send**.

### 3. Install the Integration
1. Copy the `google_sheets_monitor` folder to your Home Assistant `custom_components` directory:
   ```
   <config_directory>/custom_components/google_sheets_monitor
   ```
   If the `custom_components` directory does not exist, create it.

2. Restart Home Assistant.

---

## Configuration

Add the following to your `configuration.yaml` file:

```yaml
google_sheets_monitor:
  people:
    - name: "Alice"
      credentials_file: "alice_credentials.json"
      sheets:
        - id: "spreadsheet_id_1"
          name: "Sheet1"       # Optional, defaults to the first sheet
          scan_interval: 30    # Optional, default is 30 seconds
        - id: "spreadsheet_id_2"
          scan_interval: 60    # Optional

    - name: "Bob"
      credentials_file: "bob_credentials.json"
      sheets:
        - id: "spreadsheet_id_3"
          name: "Sheet2"       # Optional
          scan_interval: 45    # Optional
```

### Parameters

- **`people`**: A list of users, each with:
  - **`name`**: Name of the person (used in logs and events).
  - **`credentials_file`**: Path to the Google service account credentials JSON file.
  - **`sheets`**: A list of spreadsheets to monitor, each with:
    - **`id`**: The spreadsheet ID (from the URL: `https://docs.google.com/spreadsheets/d/<spreadsheet_id>/edit`).
    - **`name`**: (Optional) The subsheet name. Defaults to the first sheet if not specified.
    - **`scan_interval`**: (Optional) Scan frequency in seconds. Default: 30 seconds.

---

## Events

When a change is detected, the integration fires a `google_sheets_row_change` event with the following data:

| Field               | Description                                                                 |
|---------------------|-----------------------------------------------------------------------------|
| `person`            | The name of the person associated with the sheet.                         |
| `spreadsheet_id`    | The ID of the monitored spreadsheet.                                       |
| `sheet_name`        | The name of the monitored subsheet.                                        |
| `event_type`        | The type of change: `add`, `delete`, or `change`.                         |
| `row_number`        | The row number where the change occurred.                                 |
| `row_data`          | The data from the row after the change (for `add` or `change` events).    |

---

## Example Automation

Here’s an example automation to send a notification when a row changes:

```yaml
automation:
  - alias: "Google Sheets Change Alert"
    trigger:
      platform: event
      event_type: google_sheets_row_change
    action:
      - service: notify.notify
        data_template:
          message: >
            Person: {{ trigger.event.data.person }}
            Spreadsheet: {{ trigger.event.data.spreadsheet_id }}
            Sheet: {{ trigger.event.data.sheet_name }}
            Row: {{ trigger.event.data.row_number }}
            Event: {{ trigger.event.data.event_type }}
            Data: {{ trigger.event.data.row_data }}
```

---

## Notes

- Ensure all sheets being monitored have a **header row**.
- The service account must have access to the spreadsheet with at least **Viewer** permissions.
- If the headers in a sheet are not unique, monitoring will fail with an error. Make sure all headers in the first row are unique.

---

Let me know if you have any questions!

