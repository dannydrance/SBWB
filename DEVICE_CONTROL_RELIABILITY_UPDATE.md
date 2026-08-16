# Device control reliability update

- Remote commands are no longer removed from the server queue after being returned once.
- A command stays pending until the ESP32 explicitly ACKs it, preventing dropped HTTP responses from losing `start-uv`, `stop-uv`, heater, or other commands.
- UV and heater toggles continue to render from the actual `uvState` / `heaterState` values reported by the device.
