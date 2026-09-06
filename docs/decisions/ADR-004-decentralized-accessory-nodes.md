# ADR-004: Decentralized accessory-control nodes

- Status: Accepted
- Date: 2026-09-06
- Origin: Consolidates the accepted layout-automation ADR-001

## Context

The initial layout has approximately 20 PECO Insulfrog turnouts (SL-95,
SL-96, and SL-90 double slips) and approximately 20 signal LEDs rated at
2 V, 2 mA. The SBC also performs asset management and drives DCC through an
EX-CSB1 over a dedicated serial connection. Accessory control must therefore
avoid long servo-PWM runs, excessive voltage drop, jitter, and DCC-bus noise.

## Decision

Accessory hardware is divided into Wi-Fi-connected clusters. Each cluster has
an ESP32 and one or more PCA9685 PWM boards connected by a short, local I2C
bus. The SBC communicates with nodes over MQTT; it does not generate remote
servo PWM directly.

In MTOS, an **accessory node** is the complete local control and power unit,
not only the ESP32. It consists of:

- one ESP32 controller connected to the SBC's MQTT broker over Wi-Fi;
- one or more PCA9685 boards on a short local I2C bus;
- a fused connection to the layout's 12 V accessory-power bus;
- a local 12 V-to-5 V DC-DC converter;
- separate 5 V distribution for servos and suitable ESP32 board power;
- 3.3 V-compatible PCA9685 logic and I2C wiring;
- current-limited signal outputs and any required transistor/MOSFET drivers;
- connectors for its assigned servos, signals, feedback sensors, and other
  supported local accessories; and
- enclosure or mounting, wiring identification, protection, decoupling, and
  service access appropriate to its location.

An **accessory cluster** is the geographical group of turnouts, signals, and
other accessories served by one accessory node. The terms are related but not
interchangeable: the node is the controller/power assembly; the cluster is the
node plus the physical loads allocated to it.

Two initial cluster profiles are accepted:

| Profile | Hardware | Nominal capacity |
| --- | --- | --- |
| Standard | 1 ESP32 and 1 PCA9685 | Up to 5 turnout servos and 5 signals |
| Yard | 1 ESP32 and 2 daisy-chained PCA9685 boards | Up to 10 turnout servos and 10 signals |

An SL-90 double slip uses two independently configured servos and therefore
two PCA9685 channels. Capacity figures are planning limits, not the electrical
maximum of the PCA9685.

Turnouts use SG90 or MG90S servos. PECO over-centre springs are removed, and
0.8–1.0 mm spring-steel piano wire provides compliant linkage. Firmware moves
each turnout gradually between calibrated endpoints and disables its PWM
output after movement, using the PCA9685 full-off form equivalent to
`setPWM(channel, 0, 4096)`. The mechanism must hold position without continuous
servo torque.

## Consequences

- Short PWM and I2C wiring reduces susceptibility to drop, jitter, and noise.
- Clusters are modular and failures are confined geographically.
- No large capacitor is required at every turnout solely to compensate for a
  long shared 5 V servo feed.
- More ESP32 devices must be configured, monitored, upgraded, and secured.
- Wi-Fi addressing should use DHCP reservations where stable addresses aid
  diagnosis; correctness must not depend on a static address or eliminate
  normal network discovery and reconnect time.

The topology and mechanical approach are accepted. Pin assignments, channel
maps, calibration values, firmware, and PCB/wiring designs remain
implementation-specific configuration and require validation.
