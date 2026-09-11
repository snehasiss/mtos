# ADR-005: Accessory power distribution

- Status: Superseded by ADR-007
- Date: 2026-09-06
- Origin: Consolidates the accepted layout-automation ADR-002

## Context

The EX-CSB1 uses its own 15 V, 6 A supply for DCC. MTOS uses two SBCs: a
Cubietruck A20 and a Vicharak Axon. Distributing regulated 5 V over the whole
layout would magnify voltage drop during servo startup and previously led to
consideration of approximately 20,000 µF of bulk capacitance. Accessory loads
need a separate, serviceable power domain.

The planned accessory population is 20–30 turnout servos, approximately 30
signal LEDs, and additional loads such as building and industrial lighting and
motorized or sound-equipped trackside accessories. For example, the Broadway
Limited operating water tower specifies standard 12 V DC power for its
motorized spout and sound, but its published product page does not state its
current. The Faller chemical plant specifies two sets of item 180653 (five
warm-white LEDs per set), so it represents ten additional lighting points, not
an indivisible generic load.

## Decision

Use a dedicated regulated 12 V DC, 5–10 A accessory supply, independent of the
DCC and SBC supplies. Run a two-conductor 16 or 18 AWG accessory bus alongside,
but electrically separate from, the DCC bus. Each accessory cluster receives
12 V and uses a locally mounted LM2596 buck module, calibrated with a multimeter
to 5.0 V before electronics are connected.

An accessory node comprises one Wi-Fi/MQTT-connected ESP32, one or more local
PCA9685 boards, the 12 V bus connection and protection, a 12 V-to-5 V DC-DC
converter, power distribution, output drivers, and the connectors for its
assigned cluster of turnouts, signals, sensors, and other accessories. The
ESP32 and PCA9685 logic are continuous loads. Servo power is distributed from
the same local converter but is electrically decoupled and routed separately
from logic power.

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

## Preliminary load budget

The power design distinguishes connected load, normal continuous load,
scheduled simultaneous load, and fault/stall load. Having 20–30 servos
connected does not mean they all draw running current at once. PWM is cut off
after a turnout movement, so a correctly adjusted mechanism should not be
continuously energized.

For initial engineering—not component acceptance—use these conservative 5 V
allowances until measurements of the purchased devices replace them:

| Load | Planning allowance | Design treatment |
| --- | ---: | --- |
| ESP32 board with active Wi-Fi | 0.5 A per node | Allows radio bursts and board overhead |
| PCA9685 logic | 0.05 A per board | Excludes servos and externally driven LEDs |
| SG90/MG90S moving normally | 0.15–0.30 A per moving servo | Verify with the installed linkage |
| SG90/MG90S startup or stall | 1.0 A per servo | Conservative converter and transient allowance |
| 30 signal LEDs rated 2 mA | 0.06 A LED current total | About 0.30 W from 5 V with series resistors |

Published SG90-family measurements vary by manufacturer and clone: one tested
SG90 specification gives 140 mA no-load running current, 520 mA locked stall
current, and 5 mA stopped idle current at 4.8 V. The MG90S manufacturer states
4.8 V operation but does not publish current on its product page. Consequently,
the design uses 1.0 A per moving or stalled servo until the actual batch is
measured. Name-only estimates are unsafe because variants and counterfeit
servos are common.

At the whole-layout level:

- 30 simultaneously stalled servos would require 30 A at 5 V, or 150 W, before
  logic and conversion losses. The system is not intended to operate that way.
- Limiting ordinary operation to five simultaneous servo movements produces a
  5 A / 25 W worst-case servo allowance at 5 V. At 85% conversion efficiency,
  that is approximately 2.45 A from the 12 V bus.
- Thirty signal LEDs illuminated at 2 mA contribute only 60 mA. Additional
  signal aspects and all scenery lighting are inventoried separately.
- Each standard five-servo node should initially use a genuine, tested 5 V,
  3 A continuous converter if firmware permits only one servo to move at once.
  Each ten-servo yard node should use a tested 5 V, 5 A continuous converter,
  or split servo power into protected sub-branches. The advertised peak rating
  of a small LM2596 module is not its proven continuous enclosed rating.

Given the present population, select the upper end of the accepted accessory
supply range: **12 V, 10 A (120 W)**. This is an initial capacity decision, not
a claim that the layout will continuously consume 120 W. Approximately 2.45 A
is reserved for five concurrent worst-case servo loads, with the remaining
capacity available for node logic, measured native-12 V accessories, scenery
lighting, conversion losses, transient margin, and future additions. The final
branch schedule must demonstrate the allocation before installation; if its
calculated demand exceeds 80% of the supply's continuous rating, split the
accessories across another supply rather than consuming the reserve.

The command scheduler enforces configurable global and per-node movement
concurrency limits. Electrical protection must still tolerate or clear fault
current; software sequencing is not a fuse and cannot be the only safeguard.

## Other accessory loads

The 12 V bus may feed native 12 V scenery accessories through independent,
fused and switchable branches. The operating water tower is such a candidate,
but its current must be obtained from its instructions or measured through a
complete movement-and-sound cycle before allocating its branch. It must not be
powered through a PCA9685 output.

Building, chemical-plant, industry, yard, and engine-house lighting is treated
as a separately inventoried continuous load. Each installation records supply
voltage, measured current, quantity, driver type, dimming requirement, and
simultaneous-use assumption. Lighting may share the 12 V source when the load
and noise budget permits, but uses its own fused distribution and switching;
it does not share a servo node's 5 V logic branch by default. Reserve at least
25% spare capacity after all measured continuous accessory loads and the
allowed servo concurrency are included.

## SBC power supplies

The computer power domain remains separate from DCC and accessory motors:

| Computer | Input requirement | Reserved supply capacity |
| --- | --- | ---: |
| Cubietruck A20 | Regulated 5 V input | 5 V, 3 A (15 W), including attached storage |
| Vicharak Axon | 12 V USB-C Power Delivery; do not use 5 V | Up to 60 W for peripherals; 18–20 W covers many ordinary uses |

The preferred arrangement is a dedicated 12 V USB-C PD supply for the Axon and
a dedicated regulated 5 V, 3 A supply for the Cubietruck. Neither is connected
to the turnout/lighting accessory bus. If one central computer-only supply is
later used, allocate approximately 60 W for the Axon, 15 W for the Cubietruck,
conversion loss, and at least 20% margin: a 12 V, 10 A (120 W) source is a
practical size. It still requires a compliant 12 V USB-PD source stage and
cable for the Axon and a regulated 12 V-to-5 V converter for the Cubietruck;
passive 12 V wiring into the Axon's USB-C connector is not acceptable.

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

## Reference product information

- [Broadway Limited operating water tower](https://www.springcreekmodeltrains.com/product/broadway-limited-ho-operating-water-tower-weathered-unlettered-brown/)
- [Faller chemical plant 130175](https://www.faller.de/en/miniature-worlds/busy-world-of-business/351/chemical-plant)
- [Vicharak Axon power guidance](https://docs.vicharak.in/vicharak_sbcs/axon/axon-getting-started/)
- [Cubietruck power guidance](https://wiki.debian.org/InstallingDebianOn/Cubietruck)
- [SG90 measured electrical specification](https://www.sunfounder.com/products/sf0180-servo-motor)
- [TowerPro MG90S manufacturer specification](https://towerpro.com.tw/product/mg90s-3/)
