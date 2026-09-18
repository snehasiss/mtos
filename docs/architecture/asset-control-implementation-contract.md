# asset_control implementation contract

Date: 2026-09-17. Status: historical Phase 1 implementation contract.

> ADR-009 supersedes this contract's single-process topology, unrestricted shared
> SQLite access and runtime ownership. This remains the record of the first MAIN
> implementation and a source of device behavior and acceptance requirements.
> New work must follow the six-service control architecture and its lease,
> fencing, recovery and bounded-resource contracts.

This document refines ADR-007 and the pre-design/device-interface plans. Where
their execution details differ, this contract governs the first implementation.
It does not claim that firmware, migrations or hardware have been implemented.

The [Phase 1 low-level design](asset-control-phase-1-low-level-design.md) defines
the concrete modules, database changes, methods, HTTP endpoints, UI behaviour and
acceptance scenarios for CSB1 MAIN implementation.

## Scope and implementation order

One Flask service on `0.0.0.0:5302` uses the existing shared SQLite database.
Cubietruck owns the serial connection and accessory scheduler; Mosquitto serves
ESP32 nodes over Wi-Fi. Axon remains outside the control path.

Implement three reviewable increments:

1. DCC MAIN end to end: one runtime owner, USB selection, verified handshake,
   output awareness, roster eligibility, MAIN power, throttle, functions,
   stop/emergency stop and mobile UI. Start with fake serial transports.
2. PROG CV programming in the same UI: isolated programming-track arrangement,
   CV reads/writes, readback, timeout handling and coordinated address changes.
   Confirm physical wiring before commissioning; MAIN/PROG role switching is
   a separate decision, not implicit in selecting the Programming screen.
3. One complete accessory node: provisioned configuration, readiness, durable
   jobs, ESP32 firmware, one turnout and one signal, then multiple nodes,
   double-slips and local buffer-stop flashing. Test failure/restart behaviour.
   Water-tank control follows within this checkpoint after trigger timing is established.
   Turntables await selected hardware and a defined action set.

CV programming is Phase 2. MAIN/PROG role changes, routes, interlocking, autonomous operation
and chemical-plant control are deferred. Read-only output awareness is required
even though changing output roles is deferred. The initial HTTP-polling decision
is superseded by [the real-time control architecture](control-service-architecture.md):
React uses Socket.IO for acknowledged commands and server-pushed control events.
MQTT remains exclusive to ESP32 integration; no generic plugin framework is added.

## Runtime and shared data

Exactly one asset_control process owns device transports and scheduling. HTTP
threads submit to that owner; app imports and development reloaders must not
start additional hardware workers. Enforce lifetime process ownership, not only
a launcher lock. Serial and MQTT failures remain independent.

Enable and verify SQLite WAL during coordinated initialization; current roster
code does not explicitly enable it. Keep transactions short, with no hardware
wait inside a database transaction. Use the existing repository/migration path.

Before dispatch, atomically validate eligibility/configuration and reserve the
affected asset and relevant configuration. Both asset_manager and asset_control
must respect the reservation when changing address, node membership, component
mapping/calibration or lifecycle eligibility. Descriptive edits remain possible.
Use a control-configuration revision or deterministic fingerprint independently
of ordinary descriptive edits. Include dependency and node configuration changes
in validation. Reject duplicate physical channel assignments and ambiguous active
DCC addresses; intentional decoder consists need a later explicit policy.

Release reservations on known completion/failure with outputs cleaned up.
Uncertain execution requires reconciliation before incompatible edits or further
actuation. Restart must not silently delete such reservations. Decoder address
programming itself remains deferred; an inventory edit does not program hardware.

## DCC command contract

Power-on in v1 explicitly targets MAIN; the API/adapter must not default to an
unscoped all-output power-on. Observe output role and power where supported;
unknown or incompatible MAIN configuration prevents energizing/movement.

Normal movement requires fresh eligibility. Stop, emergency stop and power-off
have separate validation so a lifecycle edit cannot prevent stopping hardware.
Retain the address associated with an active command/session for this purpose.

Emergency stop clears pending throttle work and advances a control generation.
Requests from an older browser generation are rejected, including requests that
arrive after the stop. Resume requires explicit operator action. Coalesce pending
throttle updates per locomotive to avoid replaying obsolete slider positions.

Serial writes, command-station reports and physical feedback remain distinct.
Only populate reported fields from actual device reports. No automatic movement
or power restoration occurs after reconnect. Hardware may still be powered when
the application restarts: discover state and never equate reconnect with power off.

## Accessory commands and events

Use one vocabulary in storage, firmware and UI:

`queued → dispatched → accepted → started → completed`

Additional outcomes: `rejected`, `failed`, `expired`, `cancelled`, `uncertain`.
MQTT PUBACK is transport acknowledgement, not node acceptance or completion.
Cancellation/expiry before dispatch prevents execution. Once dispatched, a local
cancel or timeout cannot prove the output stopped; mark uncertain as appropriate.
Events must match command, node, boot and producer session. Ignore obsolete events
and never regress a terminal result because a delayed accepted/started event arrives.

Keep ADR-007 node topics and non-retained QoS 1 commands. Add `producer_session_id`
to command/event envelopes. On producer restart, require an explicit node session
handshake before new dispatch; reconcile any old in-flight action first. A node
accepts commands only from its currently established producer session.

Node readiness requires fresh online status, valid boot identity, installed
configuration revision and established producer session. Retained online messages
alone do not establish readiness. Define heartbeat/staleness thresholds in service
configuration and test them with a controllable clock.

Absolute command expiry requires a valid node clock with a defined allowed clock
error; nodes without valid time cannot execute expiring remote commands. Use local
monotonic timers for movement watchdogs. Reconnect must not replay queued commands
from a previous connection/session. Cache results for the whole command validity
and retry window; a fixed 16-entry cache alone is insufficient. Bound outstanding
work and reject new work if required deduplication records cannot be retained.
Duplicate IDs with different payloads are rejected.

## Configuration provisioning

SQLite remains authoritative; node configuration is an installed projection.
Generate a versioned node configuration containing asset IDs, component refs,
channels, calibrated targets, timing, polarity and startup policies. Provision
explicitly while idle; the node validates and installs atomically and reports the
installed revision. A mismatch blocks operation. Initial provisioning may be a
local tool/USB workflow; remote hot reconfiguration is not required for v1.

Assign stable node IDs and unique MQTT client IDs. Use per-node broker credentials
and topic ACLs: a node subscribes to its commands and publishes only its own
events/status/availability. Keep secrets outside Git. Broker listener, network
access and TLS deployment settings must be documented for the actual layout LAN.

## Sequencing and double-slips

Start with one durable actuator queue and one active actuator job globally.
Simple signal updates use the node output-state manager; buffer flashing is a
local periodic behaviour, never a queued movement or MQTT command per flash.

A PECO SL-90 is one turnout with two calibrated SG90 components. Execute them
sequentially, not simultaneously, retaining the global reservation until both
finish. State values remain `straight | diverging`; the calibrated pair defines
the v1 positions. Commission the pair against the intended physical paths.
Partial completion is uncertain and must not automatically roll back.

Derive completion timeout from all configured movement and settling times plus
transport margin. The old 2.5 s single-servo watchdog/3 s job timeout are provisional
single-actuator values, not universal double-slip limits. Timeout or lost contact
halts actuator dispatch until execution has been reconciled; it does not free
power capacity while an unreachable servo may still be running.

## Node outputs and buffer stops

One ESP32, one PCA9685 for SG90 PWM, one XL4015 for local 12 V-to-5 V conversion,
and cascaded 74HC595 registers for LEDs form a node. PCA9685 logic and 74HC595
interfaces use ESP32-compatible levels; servo V+ is separate from logic VCC.

Define output-enable wiring/defaults so boot/reset keeps outputs disabled until
safe values are loaded. Initialise and latch the entire 74HC595 output image before
enabling it. One firmware owner maintains all signal/buffer bits. Signal transitions
clear only the selected signal's aspects, latch, wait the configured break, then
set the chosen aspect while preserving other outputs. Use non-blocking timers for
servo stepping, LED flashing and reconnect. Specify and test reset/watchdog output
behaviour; a software watchdog alone cannot promise cleanup during a hung CPU.

Each PECO SL-40 buffer stop has one red LED and individual current limiting.
Proposed default: locally flash 500 ms on / 500 ms off after valid configuration
initialization. Continue through broker/SBC/Wi-Fi loss while the node is powered
and functioning. This is an autonomous indicator, not a stop/go signal aspect.
No 555 is required in the baseline. Independent flashing through an ESP32 failure
would instead require a separate flasher or suitable self-flashing LED.

Each buffer LED consumes one 74HC595 output. The existing 48 signal outputs plus
`b` buffer LEDs require at least `ceil((48+b)/8)` registers in aggregate; actual
allocation rounds up separately per node. Eight registers leave 16 aggregate
outputs before buffers are assigned. Quantity, inventory family/type/ID prefix
and exact LED/resistor circuit remain open; do not invent an inventory enum yet.

## Power and wiring checkpoint

Chemical-plant lighting is excluded from the initial control/load scope. Retain
the water-tank allowance provisionally. Count SG90s and brackets as one per ordinary
turnout and two per double-slip, plus spares. Include every powered servo's measured
idle draw: disabling PWM does not disconnect servo power. Count buffer LEDs at full
on-current for supply sizing, even if the chosen duty cycle is 50 percent.

The former 33.5 W estimate becomes 31.1 W after removing the 2.4 W plant allowance,
before adding buffer LEDs, aggregate servo idle draw and measured logic/driver
corrections. It is not a validated rating. The 12 V/5 A supply remains provisional.
Recalculate resistor values for the actual LED voltage/current and driver rail;
the previous blanket 1.5 kΩ at 5 V is not a 3.3 V output prescription.

The SVG is a component-level connection overview, not a pin-level construction
schematic. Before assembly document connector/pin numbers, logic rails, OE/reset
pull-ups, per-chip decoupling, LED polarity/current limits, fuse sizes and common
node ground. MAIN and PROG are separate command-station outputs and must not be
shown connected together.

## Verification and bounded history

Use fake serial/MQTT transports and temporary databases for automated tests.
Cover concurrent roster edits, duplicate/delayed/out-of-order messages, producer
and node restarts, uncertain execution, double-slip partial failure, emergency
stop followed by delayed throttle, and flashing during servo/network activity.
Commission real outputs separately with recorded hardware/firmware and measurements.

Keep operational history bounded by configurable age/count limits; preserve
unresolved jobs and their evidence until reconciliation. Do not store unlimited
serial/MQTT transcripts. ADR-009 defines the Version 1 retention defaults.

## Hardware references

- [PECO SL-40](https://peco-uk.com/products/buffer-stop-railbuilt2)
- [Nexperia 74HC595 data sheet](https://assets.nexperia.com/documents/data-sheet/74HC_HCT595.pdf)
- [NXP PCA9685 data sheet](https://www.nxp.com/docs/en/data-sheet/PCA9685.pdf)
