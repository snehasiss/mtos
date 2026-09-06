# Review of the original layout-automation ADRs

- Reviewed: 2026-09-06
- Sources: `ADR-001-layout_automation.md`, `ADR-002-layout_automation.md`,
  `ADR-003-MessageBroker.md`, and `ADR-004-System-design.md`
- Result: architecture retained; electrical, state, and message-contract gaps
  made explicit in ADR-004 through ADR-006 and the layout architecture guide

## What the four documents establish

The documents describe one coherent accessory subsystem:

- An SBC runs the core Python application and local Mosquitto broker.
- The SBC controls DCC through an EX-CSB1 on dedicated serial, powered by its
  own 15 V, 6 A supply.
- Approximately 20 PECO Insulfrog SL-95, SL-96, and SL-90 turnouts and about
  20 signal LEDs rated 2 V, 2 mA are distributed among ESP32/PCA9685 clusters.
- Standard clusters plan for five servos and five signals; yard clusters use
  two daisy-chained PWM boards and plan for ten of each.
- SG90/MG90S servos use 0.8–1.0 mm spring-steel piano-wire linkages after PECO
  over-centre springs are removed. An SL-90 uses two independent servos.
- A separate 12 V, 5–10 A regulated supply feeds a 16/18 AWG accessory bus;
  each cluster converts locally to 5.0 V with an LM2596.
- Mosquitto, Paho MQTT, retained commands, broker persistence, and QoS 1 were
  selected; Node-RED was rejected as a core dependency.
- The reference firmware uses a local, short I2C bus, PCA9685 at 50 Hz, gradual
  servo movement, and full PWM cutoff after the movement.

The central architectural choice is sound: geographically distributed nodes
keep PWM, I2C, and high-current 5 V wiring short, while the direct DCC serial
path remains independent of Wi-Fi accessory control.

## Required corrections and clarifications

### Electrical design

The source power ADR says the local 5 V rail feeds ESP32 power, PCA9685 logic
`VCC`, and servo `V+`. This cannot be adopted literally without checking the
exact boards. An ESP32 uses 3.3 V GPIO, and many PCA9685 boards pull SDA/SCL up
to logic `VCC`; a 5 V logic rail could therefore put 5 V on ESP32 I2C pins.
The integrated decision separates 5 V servo power from 3.3 V PCA logic and
requires use of the documented ESP32 board power input.

The 2 V, 2 mA LED rating is a load specification, not a drive voltage. Each LED
needs a calculated current-limiting resistor. Driver transistors or MOSFETs may
be needed depending on common-anode/cathode wiring, cable length, PWM board
limits, and aspect grouping.

The original design contains no branch fusing, polarity protection,
decoupling, connector specification, earthing/wiring practice, or current and
thermal calculation. LM2596 modules are normally non-isolated, and describing
one as a local noise filter is not enough. Servo stall and simultaneous-start
tests are required. The earlier 20,000 µF concern is useful context but does
not by itself prove the local-buck design needs no bulk capacitance.

### State and messaging

The retained `/set` payload was described as preventing turnout misalignment
when a node reboots. It only restores the last transmitted desire; it cannot
prove the physical position. Replaying it can itself cause unexpected movement.
The revised design distinguishes desired, acknowledged, reported, observed,
and available state and requires an explicit startup policy.

QoS 1 means at-least-once delivery, not exactly once. Duplicate commands are
normal, so nodes must deduplicate or safely repeat operations. Broker
persistence improves transport continuity but is not an application database.
SQLite remains authoritative.

The prototype topics expose a physical channel as identity and carry only
integer `0`/`1`. They lack command IDs, timestamps/expiry, configuration
revision, acknowledgement, errors, and reported state. They also conflate
turnout geometry (`straight/main`, `diverging`) and signal safety semantics
(`dark/stop`, `lit/clear`). MTOS needs stable logical IDs and a versioned
contract before these examples become an API.

Authentication, authorization, and availability behavior were unspecified.
Per-node credentials, topic ACLs, Last Will, birth/health messages, and an
explicit response to broker or Wi-Fi loss are now required.

### Firmware reference

The example is valuable because it records PCA9685 address `0x40`, 50 Hz PWM,
I2C at 100 kHz, pulse endpoints 150/450, step size 3, 12 ms step delay, and
50 ms settle time. These must be configuration and calibration values, not
fleet-wide constants.

Other prototype behaviors should not move unchanged into production:

- `toInt()` maps malformed payloads to zero instead of rejecting them.
- hard-coded substring tests are fragile topic parsing;
- a blocking reconnect loop with five-second delays can stall other work;
- initializing every cached servo position to the minimum invents knowledge
  after reboot;
- a single 16-entry array does not cover two addressed PCA9685 boards without
  explicit board/channel mapping;
- Wi-Fi credentials and broker addresses must be provisioned, not compiled as
  shared source constants; and
- success must be acknowledged only after the action, with failures reported.

### Document consistency

The source system diagram labels signals as `2 V / 2 mA LED`, while its sample
code drives channel PWM as 4095 or 0 without documenting a resistor or driver.
The hardware design must reconcile that before wiring.

The source describes DHCP reservations/static addresses as providing “zero
initialization latency.” Reservations make addresses predictable but do not
remove association, DHCP, broker connection, or subscription latency.

The troubleshooting section of the system-design document ends after listing
possible causes for node lag and supplies no corresponding actions. The new
architecture guide completes the diagnostic sequence without treating DHCP or
LM2596 drift as the only explanations.

## Decisions still needed before implementation

1. Specify the versioned MQTT topics and payload schemas, command expiry,
   retained-message policy, acknowledgement/error behavior, and compatibility
   rules.
2. Define turnout and signal domain models, including double-slip coordination,
   signal aspects, routes/interlocking, and safe startup/failure states.
3. Produce a node provisioning and configuration format with logical IDs,
   physical mappings, calibration, credentials, and firmware/config revisions.
4. Complete electrical calculations and a wiring/protection schematic for each
   cluster profile, then bench-test startup, stall, noise, brownout, and network
   failure cases.
5. Define firmware update, health telemetry, logs, recovery, and replacement
   procedures for the increased node count.

## Traceability

| Source | Integrated destination |
| --- | --- |
| Layout automation ADR-001 | ADR-004 and layout architecture: clusters, turnout hardware, movement, cutoff |
| Layout automation ADR-002 | ADR-005 and layout architecture: supplies, bus, local conversion, validation |
| Message broker ADR-003 | ADR-006: Mosquitto/Paho, QoS, persistence, Node-RED boundary |
| System design ADR-004 | Layout architecture and this review: combined topology, examples, troubleshooting |

The four source files were reviewed as design inputs and were not modified.
