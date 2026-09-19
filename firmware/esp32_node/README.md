# MTOS ESP32 accessory-node firmware

This PlatformIO project implements the node side of `mtos_mc` for one ESP32,
one PCA9685, cascaded 74HC595 registers and the isolated water-tank relay.
It has not been electrically commissioned.

Before building, copy but do not commit:

```bash
cp include/secrets.h.example include/secrets.h
cp include/node_config.h.example include/node_config.h
```

Replace every Wi-Fi/MQTT secret, pin, mapping, servo endpoint, LED mask and
water-tank timing with the constructed-node values. The example configuration
is documentation, not a safe layout configuration.

The firmware provides:

- unique boot identity, retained availability/LWT and five-second status;
- MC producer-session handshake and configuration-revision validation;
- command-expiry time derived from the fenced MC handshake, without requiring
  public NTP or Internet access on the layout network;
- QoS 1 command subscription and bounded terminal-result deduplication;
- one non-blocking actuator runner per node;
- sequential SG90 movement with settling and PCA9685 full-off cleanup;
- persisted last-known turnout state; unknown state fails closed until supervised
  commissioning establishes the first position;
- a single 74HC595 output-image owner and signal break-before-make;
- local buffer flashing without MQTT traffic per flash;
- a normally-open water-tank relay pulse and non-retriggerable cycle window;
- relay-open, PWM-off and signal-safe initialization.

Build when PlatformIO is installed:

```bash
cd firmware/esp32_node
pio run
```

Do not flash a node connected to servos, signal LEDs or the water tower during
the first firmware test. Commission in this order: bare ESP32 and broker,
74HC595 with test LEDs, PCA9685 without servo linkage, one unloaded SG90, one
turnout with current measurement, then the isolated water-tank relay. Verify
GPIO boot levels, OE behavior, coil flyback, supply polarity and branch fuses.

After physically placing and verifying a turnout, establish its first persisted
position over the USB serial console at 115200 baud:

```text
position T001 straight
position T001
clear T001
```

The first command records an observed position without moving a servo, the
second reads it, and `clear` returns the turnout to fail-closed unknown state.
Commands are rejected while an actuator sequence is running. This local-only
commissioning path is intentional; MQTT cannot invent a first physical position.

Live MQTT is disabled in the host service by default. Enable it only for a
supervised test with `MTOS_MQTT_ENABLED=1` and configured broker credentials.

## Pre-commissioning software gaps

The firmware is not yet protocol-complete for physical operation:

- PubSubClient publishes events and retained status at QoS 0. The MTOS target
  contract requires QoS 1 node events, so select/implement a publisher that can
  provide it before commissioning.
- The 64-entry cache stores terminal results for 60 seconds, but an identical
  retry received while an execution is active currently receives `busy` instead
  of the existing `accepted/started` state.
- Publish return values, broker acknowledgements and reconnect fault injection
  still require explicit tests.
- PlatformIO compilation, board pin validation and every electrical/output test
  remain pending because the hardware/toolchain is not present.

These gaps are safe in the present broker-offline development mode. They are not
authorization to connect servos, LEDs or the water tower.
