# Real-time operator monitoring update

- Device header, telemetry/status block and remote controls poll independently every 1 second via HTMX.
- ESP32 publishes changed hardware state immediately (250 ms debounce) and retains a 1 second HTTP/HTTPS heartbeat for command pickup/connectivity.
- Nano-to-ESP32 UART remains change-only; unchanged relay/sensor state is not repeatedly transmitted.
- Added live operator fields: IR sensor, raw limit-switch closed confirmation, lid state-machine phase, lock-solenoid state, UV-C and heater state.
- Remote-control toggle labels always represent confirmed device state and explicitly show the next action.
