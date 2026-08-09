# SBWB August 2026 Integration Update

## Web application
- Added per-device PDF reporting and full-system PDF reporting with charts and tables.
- Added ReportLab to `requirements.txt`.
- Added real-time System & Connectivity panel, independently refreshed every 2 seconds with HTMX.
- Changed interlock, UV and heater controls to state-aware toggle switches. Switch position and color use the latest telemetry-confirmed state.
- Reduced online timeout to 12 seconds to align with the ESP32 2-second heartbeat.
- Added SmartBin identity/connectivity fields: system name, system version, ESP MAC, Wi-Fi SSID and IP address.
- Telemetry location continues to update `location_name`.

## Required database update
Run:

    python manage.py migrate

This applies migration `0007_smartbin_system_identity_connectivity.py`.

## PDF dependency
Install the updated requirements before running the application:

    pip install -r requirements.txt

If your environment already contains the other packages, the new PDF dependency is `reportlab==4.4.9`.

## ESP32 integration
Use the matching updated ESP32 firmware package. It sends the system identity, current Wi-Fi/IP and editable location with telemetry.
