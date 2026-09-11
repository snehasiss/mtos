# ADR-007: Stationary assets, control network, and power management

- Status: Accepted; equipment currents require commissioning measurements
- Date: 2026-09-07
- Supersedes: ADR-004, ADR-005, and ADR-006

## Context

MTOS must inventory and operate stationary railroad assets without requiring
JMRI, WiThrottle, or another external control application. The initial scope is
20 turnouts, 20 signals, and two representative trackside installations. The
design must run on modest hardware, preserve the direct DCC control path, avoid
simultaneous servo inrush, and distinguish durable asset/configuration data
from commands and observed operational state.

The Cubietruck A20 (`SBC-A20`) is the physical control authority. The Vicharak
Axon is reserved for SLM workloads used later for autonomous mainline operation
or instruction-based yard operation. An Axon-generated plan is a request to the
Cubietruck application; the Axon never bypasses validation or publishes
hardware commands directly.

## Decision

### Asset identity and categories

Every physical asset has a canonical, human-readable identifier consisting of
one uppercase type letter and three decimal digits:

```regex
^[A-Z][0-9]{3}$
```

The stationary-asset prefixes are:

| Prefix | Asset type | Example |
| --- | --- | --- |
| `T` | Turnout | `T012` |
| `G` | Signal | `G003` |
| `N` | Accessory node | `N001` |
| `E` | Trackside equipment | `E002` |

`G` is used for signals because `S` is easily confused with `5`. Elsewhere in
the inventory, `L` identifies locomotives, `C` rolling-stock cars, and `M`
Maintenance of Way assets. The identifier expresses asset category only;
manufacturer, model, subtype, location, and capabilities are attributes.

Command and operation IDs are transactional identifiers and do not use the
asset-number format. They must be globally collision-resistant.

### Data ownership

SQLite on the Cubietruck is authoritative. Durable asset and configuration
data includes:

- asset ID, type, description, location, and lifecycle;
- accessory-node membership;
- PCA9685 board address and output-channel mapping;
- turnout endpoints, direction, movement timing, and safe-state policy;
- signal type, supported aspects, LED mapping, and safe aspect;
- trackside-equipment voltage, current, driver, actions, and safety policy; and
- node firmware version and configuration revision.

Commands, acknowledgements, reported state, failures, and operation history
are transactional data linked to assets by their canonical IDs. An MQTT
retained message or ESP32 variable is not the authoritative asset record.

## Stationary asset models

### Turnouts

The initial inventory contains 20 PECO Insulfrog turnouts, including SL-95,
SL-96, and SL-90 double slips. Each actuator is an SG90 9 g servo. A turnout
uses the domain states `straight` and `diverging`; a double slip has two
independently mapped and calibrated actuators coordinated by its turnout
behavior.

PECO over-centre springs are removed. Each servo uses a compliant linkage made
from 0.8–1.0 mm spring-steel piano wire. Firmware sweeps slowly between
calibrated endpoints, permits a settling interval, and then disables PCA9685
PWM using the full-off operation equivalent to `setPWM(channel, 0, 4096)`.
The mechanism must hold position without continuous servo torque.

### Signals

The initial signal inventory is:

| IDs | Quantity | Signal type | Valid aspects |
| --- | ---: | --- | --- |
| `G001`–`G012` | 12 | Yard ground signal, two aspect | `stop`, `go` |
| `G013`–`G020` | 8 | Mainline analog signal, three aspect | `stop`, `slow`, `go` |

Aspect values are lowercase domain values. A two-aspect signal rejects `slow`,
and every signal rejects an unknown value rather than silently choosing an
aspect. `stop` is the safe aspect after invalid commands or uncertain route
state. Physical colors, polarity, resistors, drivers, PCA9685 channels, and
brightness are deployment configuration rather than domain values.

The initial signal LEDs are rated approximately 2 V, 2 mA. Every LED has an
individual calculated current-limiting resistor. From 5 V, a 2 V LED at 2 mA
uses 1.5 kΩ. Transistor or MOSFET drivers are used when electrical topology,
load, or wiring makes direct PCA9685 drive unsuitable.

### Trackside equipment

Initial power planning includes two assets:

| ID | Installation | Electrical treatment |
| --- | --- | --- |
| `E001` | Broadway Limited operating water tower | Native 12 V motor/sound equipment; provisional 1 A branch; operate through its supplied control interface or an isolated dry contact |
| `E002` | Faller chemical plant lighting | Two sets of five warm-white LEDs, ready for 12–16 V AC/DC; provisional 0.2 A total at 12 V |

The published water-tower information does not state current. Its complete
movement-and-sound cycle must be measured before final fuse selection. The
water-tower motor is not driven from a PCA9685 output. Additional lighting,
turntables, and animated installations are added later as independently
inventoried `E` assets with measured loads and appropriate controllers.

## Accessory nodes and network

An accessory node is the complete local control and power assembly. It
contains:

- one ESP32 CP2102 dual-core Wi-Fi development board with 30 pins;
- one PCA9685 16-channel servo/PWM driver for a standard node;
- one LM2596 12 V-to-5 V buck converter;
- a fused 12 V accessory-bus input;
- separate local routing for logic, servo, and driven outputs;
- 3.3 V-compatible PCA9685 logic/I2C wiring;
- current-limited signal outputs and required drivers;
- labelled, detachable load and power connectors;
- normal converter-specified input/output decoupling; and
- serviceable mounting or an enclosure.

An accessory cluster is the geographical collection of turnouts, signals,
sensors, and equipment served by one node. It is not another controller.

Four nodes support the initial installation. The 12 two-aspect and eight
three-aspect signals require 48 independently driven aspect outputs. Together
with 20 servo outputs, the installation needs 68 PCA9685 channels. Five
16-channel boards provide 80 channels and leave 12 spare:

| Controllers | PWM boards | Assigned channels | Spare channels |
| ---: | ---: | ---: | ---: |
| 4 ESP32 nodes | 5 PCA9685 boards | 20 servo + 48 signal aspect = 68 | 12 |

One node therefore has two addressed, daisy-chained PCA9685 boards. The final
geographical channel map may place the expansion board on a different node or
redistribute boards, but it must preserve capacity for every individual signal
aspect rather than count one channel per signal mast.

The ESP32 communicates with Mosquitto on the Cubietruck using MQTT over Wi-Fi.
The ESP32-to-PCA9685 connection is a short local I2C bus. DHCP reservations may
provide stable addresses for diagnosis, but asset and MQTT identity use `Nnnn`
IDs and do not depend on IP addresses.

Locomotive and track-power control remain on the dedicated Cubietruck-to-
EX-CSB1 serial path. MQTT or Wi-Fi failure can make stationary accessories
unavailable but must not interrupt that serial path.

## MQTT command protocol

The baseline is MQTT 3.1.1 compatibility, Mosquitto on the Cubietruck, Paho in
the producer, and an ESP32 MQTT client. MQTT shared subscriptions are not used:
nodes are tied to physical loads and are not interchangeable workers.

Each node subscribes to:

```text
mtos/v1/nodes/{node_id}/commands
```

It publishes to:

```text
mtos/v1/nodes/{node_id}/events
mtos/v1/nodes/{node_id}/availability
mtos/v1/nodes/{node_id}/status
```

Commands use QoS 1 and are not retained. Availability uses a retained online
message and a Last Will offline message. At boot, a node generates a new random
`boot_id` and publishes its node ID, boot ID, firmware version, and
configuration revision. Every command targets the current boot ID so queued
commands from a previous node session are rejected.

Example turnout command:

```json
{
  "schema": "mtos.turnout-command.v1",
  "command_id": "019c...",
  "operation_id": "019d...",
  "sequence": 3,
  "node_id": "N001",
  "boot_id": "a4d31f76",
  "accessory_id": "T012",
  "desired_state": "diverging",
  "configuration_revision": 12,
  "issued_at": "2026-09-07T12:30:00Z",
  "expires_at": "2026-09-07T12:30:05Z"
}
```

Node application events follow:

```text
accepted -> started -> completed
                     -> failed
         -> rejected
```

MQTT `PUBACK` confirms protocol receipt, not physical completion. The producer
releases a scheduled resource only after receiving the node's `completed`
event. Without a feedback sensor, `completed` means the configured output
sequence finished and PWM was disabled; it does not prove point or signal
position.

QoS 1 permits duplicate delivery. During one boot session, each node caches at
least its 16 most recent command results by `command_id`. A duplicate in
progress republishes current status; a completed duplicate republishes the
cached result without moving the servo again. A boot-ID mismatch,
configuration-revision mismatch, expired command, unsupported state/aspect, or
unknown asset is rejected.

## Scheduling and failure recovery

The single authoritative stationary-asset scheduler runs in the producer on
the Cubietruck and persists its operation queue in SQLite. The initial global
resource limit is:

```text
turnout-servo capacity = 1
```

If seven turnouts must change, the producer publishes one command, waits for
completion, and only then publishes the next. Nodes do not coordinate a
distributed MQTT lock. Signal LED changes do not consume the servo resource.

For a route, the producer:

1. commands protecting signals to `stop` and waits for completion;
2. validates route and interlocking preconditions;
3. moves required turnouts one at a time;
4. confirms every reported result;
5. re-evaluates the route; and
6. commands the authorized signal to `slow` or `go`.

Initial timeout policy is:

| Stage | Timeout | Action |
| --- | ---: | --- |
| MQTT publish acknowledgement | 1 s | Retry the same command ID once |
| Node `accepted` event | 1 s | Retry the same command ID once |
| `accepted` to `started` | 0.5 s | Mark the command abnormal and halt the operation |
| Servo output watchdog | 2.5 s | Node disables PWM locally |
| Producer completion timeout | 3 s | Halt; mark turnout state unknown |

After timeout, node loss, or restart, the producer does not automatically
advance the sequence or replay an old movement. The route is interrupted,
protecting signals remain at `stop`, the affected turnout becomes operationally
unknown, and reconciliation or an explicit new command is required. A
Cubietruck restart reconstructs interrupted operations from SQLite but does not
re-execute them automatically.

## Power architecture and budget

Power domains are separate:

| Domain | Supply |
| --- | --- |
| DCC and EX-CSB1 | Dedicated 15 V, 6 A |
| Cubietruck A20 | Dedicated regulated 5 V, 2 A (10 W) through barrel jack |
| Vicharak Axon | Dedicated 12 V, 5 A, 60 W USB-C Power Delivery |
| Stationary accessories | Dedicated regulated 12 V, 5 A (60 W) initially |

The Axon supply must negotiate the required 12 V USB-PD profile. Passive 12 V
wiring into USB-C is prohibited. The Cubietruck allocation assumes no
substantial USB- or SATA-powered load; such additions require its supply budget
to be revisited.

The accessory supply feeds a parallel two-conductor 16 or 18 AWG 12 V bus,
electrically separate from the DCC bus. Each node converts locally to 5.0 V
using its LM2596. Five volts feeds SG90 `V+` and the documented 5 V/VIN input of
the ESP32 board. PCA9685 logic `VCC` is 3.3 V where the board's I2C pull-ups are
referenced to it. Cluster grounds are common because the selected converter is
non-isolated.

The initial peak planning calculation is:

| Load | Planning power |
| --- | ---: |
| Four ESP32 boards, 0.5 A each at 5 V | 10.0 W |
| Five PCA9685 boards, 0.05 A each at 5 V | 1.25 W |
| One SG90 startup/stall allowance, 1.0 A at 5 V | 5.0 W |
| Twenty simultaneously illuminated 2 mA signal LEDs | 0.2 W |
| Approximate LM2596 conversion loss | 2.9 W |
| `E001` water tower provisional allowance | 12.0 W |
| `E002` chemical-plant lights provisional allowance | 2.4 W |
| **Calculated peak** | **33.8 W** |
| **Peak with 25% reserve** | **42.2 W / 3.52 A at 12 V** |

A 12 V, 5 A supply provides 60 W and approximately 18 W of unallocated
capacity above the current reserved peak. Additional trackside assets trigger
a revised load schedule; the response may be a 12 V, 10 A supply or a separate
protected power zone.

No 1,000 µF or larger servo reservoir capacitor is required by this design,
because only one SG90 is commanded at a time and 5 V is generated locally.
This does not remove the converter manufacturer's required decoupling. The
actual SG90 batch must be measured at normal movement and stall before final
branch protection is selected.

Each node and trackside-equipment branch is independently fused or protected,
has reverse-polarity protection where applicable, labelled connectors, and
accessible measurement points. Software sequencing limits intended load but
does not replace a fuse or protect against a shorted cable or failed servo.

## Initial bill of materials

| Item | Quantity | Initial specification |
| --- | ---: | --- |
| Stationary-accessory supply | 1 | Regulated 12 V, 5 A, 60 W |
| Fused DC distribution block | 1 | At least 8 branches plus expansion |
| Main accessory bus | As installed | Two-conductor 16/18 AWG |
| ESP32 CP2102 dual-core 30-pin board | 4 | One per node |
| PCA9685 16-channel board | 5 | One per node plus one addressed expansion board |
| LM2596 buck converter | 4 | Tested 5 V, 3 A continuous node output |
| Node input protection | 4 sets | Fuse/PTC, polarity protection, disconnect |
| Node enclosure or mounting plate | 4 | Serviceable and labelled |
| SG90 9 g servo | 20 plus spares | Five installed per node |
| Servo bracket and linkage | 20 sets | Includes 0.8–1.0 mm piano wire |
| Signal LED aspect circuits | 48 | 24 for 12 two-aspect and 24 for 8 three-aspect signals |
| 1.5 kΩ LED resistor | 48 | One per 2 V/2 mA aspect; appropriate voltage and power rating |
| Signal driver channels | 48 | Direct PCA9685 drive only where electrically validated; otherwise transistor/MOSFET stages |
| Isolated dry-contact interface | At least 1 | Water-tower trigger |
| Trackside fused branches | 2 initially | One per `E` asset |
| Terminal blocks, connectors, wire, labels | As installed | Sized and polarized for each branch |

The table is a system BOM, not yet a purchase order. Exact fuse ratings,
converter/module acceptance, number of signal LEDs, and connector quantities
follow the completed channel map and commissioning measurements.

## Consequences

- All stationary equipment participates in the same asset, configuration, and
  transactional-state model.
- Logical IDs remain stable when nodes, PCA boards, or channels are replaced.
- Central sequencing reduces normal servo peak demand and avoids a distributed
  locking protocol across ESP32 nodes.
- Failure is conservative: routes stop and uncertain turnout state is exposed.
- Direct locomotive operation remains independent of the Wi-Fi accessory path.
- Four local nodes add firmware, provisioning, security, monitoring, and
  maintenance responsibilities.
- The initial 60 W accessory supply is sufficient only for the stated two
  trackside assets; expansion requires recalculation.

## Alternatives rejected

- **MQTT shared subscriptions:** the broker selects one subscriber, but only
  the node physically wired to an asset can execute its command.
- **A shared distributed movement token:** lease, reboot, duplicate, and lost-
  release handling adds a distributed lock manager where one producer already
  owns the operation.
- **Retained turnout commands:** a retained desire can replay after restart and
  is not proof of physical state.
- **All servos moving together:** requires much larger transient capacity and
  provides no operational advantage for the initial layout.
- **Axon as a second hardware producer:** permits conflicting authorities and
  bypasses deterministic validation on the Cubietruck.
- **One supply for computers, DCC, servos, and lighting:** couples motor noise
  and faults into critical computing and locomotive control.

## References

- [MQTT Version 5.0 specification: subscription and QoS semantics](https://docs.oasis-open.org/mqtt/mqtt/v5.0/mqtt-v5.0.html)
- [Broadway Limited operating water tower](https://www.springcreekmodeltrains.com/product/broadway-limited-ho-operating-water-tower-weathered-unlettered-brown/)
- [Faller chemical plant 130175](https://www.faller.de/en/miniature-worlds/busy-world-of-business/351/chemical-plant)
- [Faller warm-white LEDs 180653](https://www.faller.de/anlagenbau/licht-elektronik/1391/5-leds-warm-weiss)
- [Vicharak Axon power guidance](https://docs.vicharak.in/vicharak_sbcs/axon/axon-getting-started/)
- [Cubietruck power guidance](https://wiki.debian.org/InstallingDebianOn/Cubietruck)
- [SG90 measured electrical specification](https://www.sunfounder.com/products/sf0180-servo-motor)
