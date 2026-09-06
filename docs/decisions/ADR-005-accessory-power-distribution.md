# ADR-005: Accessory power distribution

- Status: Accepted, pending electrical validation
- Date: 2026-09-06
- Origin: Consolidates the accepted layout-automation ADR-002

## Context

The EX-CSB1 uses its own 15 V, 6 A supply for DCC, and the SBC uses its own
wall adapter. Distributing regulated 5 V over the whole layout would magnify
voltage drop during servo startup and previously led to consideration of
approximately 20,000 µF of bulk capacitance. Accessory loads need a separate,
serviceable power domain.

## Decision

Use a dedicated regulated 12 V DC, 5–10 A accessory supply, independent of the
DCC and SBC supplies. Run a two-conductor 16 or 18 AWG accessory bus alongside,
but electrically separate from, the DCC bus. Each accessory cluster receives
12 V and uses a locally mounted LM2596 buck module, calibrated with a multimeter
to 5.0 V before electronics are connected.

At a cluster:

- 5 V feeds servo power (`V+`) and any board input explicitly designed for 5 V.
- ESP32 power follows the selected board's documented `VIN`/`5V` input; 5 V
  must never be connected to a 3.3 V-only pin.
- PCA9685 logic `VCC` is connected to 3.3 V when its I2C pull-ups are referenced
  to `VCC`, keeping SDA and SCL safe for the ESP32.
- Grounds for the ESP32, PCA9685 logic, servo supply, and signal drivers are
  common within the non-isolated cluster.
- Signal LEDs receive individual current-limiting resistors and, where load or
  wiring warrants it, transistor/MOSFET drivers; a bare LED is not connected
  directly across a PWM output and supply.

Each branch requires an appropriately rated fuse or resettable protection,
reverse-polarity protection, local bulk and high-frequency decoupling, labelled
connectors, and strain relief. Wire gauge, fuse values, buck thermal capacity,
voltage-drop margin, servo stall current, simultaneous movement policy, and
supply headroom must be calculated for the installed topology.

## Consequences

- High-current 5 V paths stay short and local.
- Cluster faults and voltage drop are easier to isolate and measure.
- The 12 V bus, protection devices, buck converters, and calibration add parts
  and commissioning work.
- An LM2596 module is normally non-isolated and must not be assumed to suppress
  all conducted servo noise; layout testing is required.

This ADR does not approve any particular low-cost module or wiring assembly for
unattended use. A documented bench test under startup, stall, and simultaneous
movement conditions is required before the design is considered electrically
complete.
