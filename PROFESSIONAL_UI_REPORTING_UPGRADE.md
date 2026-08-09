# SBWB Professional UI & Reporting Upgrade

## What changed

- Professional secure login experience with clearer system identity and operator access.
- Refined global navigation and visual design.
- Dashboard now includes fleet summary metrics, a current device fill-level chart, live device registry, alerts and links to analytics/reports.
- Device detail page now includes historical charts for:
  - fill level
  - gas concentration
  - ambient temperature
  - heating-element temperature
  - humidity
- Status page is now a system analytics and reporting workspace with:
  - 24-hour / 7-day / 30-day / 90-day ranges
  - system telemetry trend chart
  - alert-state chart
  - device comparison chart
  - per-device report links
  - full-system export
- Added historical telemetry storage (`TelemetryRecord`).
- Historical sampling is rate-limited to 30 seconds, while the live SmartBin record still updates on each heartbeat. Alert-state changes are archived immediately.
- Added per-device and full-system CSV report exports.
- Added JSON analytics endpoints so charts refresh their data without full-page reloads.
- Removed hard-coded fake diagnostic values from the old status page.

## Important first run

From the project directory, activate your existing virtual environment and run:

```bash
python manage.py migrate
python manage.py runserver
```

The migration `home/migrations/0006_telemetryrecord.py` creates the historical telemetry table.

## New routes

- `/status/` — system analytics and reporting
- `/api/analytics/` — system analytics JSON
- `/api/device/<id>/analytics/` — device analytics JSON
- `/reports/system.csv?days=30` — full-system report
- `/reports/device/<id>.csv?days=30` — individual-device report

## Reporting behavior

Historical charts begin accumulating after the new migration is applied and new telemetry arrives. Existing SmartBin records only contain the latest measurement, so past data from before this upgrade cannot be reconstructed automatically.

## Real-time behavior

The dashboard and live device telemetry continue using HTMX partial updates instead of full page refreshes. Historical chart datasets refresh every 15 seconds using the analytics JSON endpoints, so charts update without repainting the complete page.


## August 2026 control, PDF and device identity update
- Added professional PDF export for individual devices and the full system.
- Remote controls now use state-aware toggle switches for interlock, UV and heater. Toggle position/color is derived from latest device telemetry.
- System & Connectivity is independently HTMX-polled every 2 seconds.
- Added server-side system metadata: system name, version, ESP MAC, connected Wi-Fi SSID and IP address.
- ESP32 About page transmits these identity/connectivity fields plus editable device location.
- Apply migration `0007_smartbin_system_identity_connectivity.py` before use.
