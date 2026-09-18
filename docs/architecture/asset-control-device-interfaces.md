# asset_control device-interface plan

> **Historical boundary note.** The device semantics below remain applicable,
> but ADR-009 assigns DCC ownership to `mtos_dcc`, accessory execution to
> `mtos_mc`, and authoritative commands/jobs to `mtos_core`. It supersedes the
> single-service, shared-database and polling assumptions in this document.
>
> The [2026-09-17 implementation contract](asset-control-implementation-contract.md)
> governs execution details: MAIN-scoped power, accepted/started events, producer
> sessions, configuration provisioning, reservations and buffer-stop indicators.
> The finalized service contract is now
> [mtos_mc scope and low-level design](mtos-mc-module.md); it governs where this
> earlier proposal leaves concurrency, persistence or readiness open.

- **Date:** 2026-09-14
- **Status:** Proposed contracts for review; no implementation

## Why two adapters are different

The EX-CSB1 is one locally attached, continuously read serial device. A normal
command should be sent immediately and correlated with whatever response DCC-EX
provides. ESP32 nodes are multiple network devices that may disconnect, reboot,
duplicate QoS 1 delivery, and complete mechanical actions later. Hiding both
behind a single generic `send()` interface would erase necessary semantics.

`asset_control` therefore has two explicit ports:

```text
DccCommandStation       synchronous, one serial owner, bounded response
AccessoryNetwork        asynchronous, durable jobs, MQTT acknowledgements
```

They may share application-level validation and state vocabulary, but not a fake
common transport abstraction.

See the [component connection diagram](../images/asset-control-connections.svg)
for the DCC path, accessory power conversion, servo path, signal path, and machine
driver boundary.

## DccCommandStation interface

Proposed application-facing operations:

```python
class DccCommandStation(Protocol):
    def connect(self, selection: SerialSelection | None = None) -> DeviceStatus: ...
    def disconnect(self) -> DeviceStatus: ...
    def status(self) -> DeviceStatus: ...
    def set_main_power(self, state: PowerState) -> CommandResult: ...
    def set_throttle(
        self, address: int, speed: int, direction: Direction
    ) -> CommandResult: ...
    def set_function(
        self, address: int, number: int, active: bool
    ) -> CommandResult: ...
    def stop_locomotive(self, address: int) -> CommandResult: ...
    def emergency_stop(self) -> CommandResult: ...
```

The interface accepts typed domain values, never raw `<...>` strings. The DCC-EX
adapter beneath it owns:

- USB serial discovery and explicit selection;
- 115200-baud port lifecycle;
- framing partial/noisy byte streams into `<...>` messages;
- command encoding and response parsing;
- one writer/scheduler and request correlation;
- readiness handshake and identity/capability capture;
- clearing queues and pending requests on disconnect/error;
- bounded diagnostics without exposing command injection.

### Device selection

Development may select an explicit macOS device path. Cubietruck should use a
stable udev-created path such as `/dev/csb1`, derived from the USB bridge's stable
attributes where available. Discovery reports device, description, manufacturer,
VID, PID, and serial number, but those values identify a USB bridge—not by
themselves a verified EX-CSB1. Readiness requires a valid DCC-EX identity exchange.
If automatic discovery finds zero or multiple candidates, it fails visibly rather
than guessing or opening all ports.

### State and result

```json
{
  "connection": "ready",
  "device": {
    "adapter": "dcc_ex",
    "port": "/dev/csb1",
    "identity": "DCC-EX ...",
    "session_id": "runtime-generated",
    "last_seen": "2026-09-14T00:00:00Z"
  },
  "power": "on",
  "stale": false
}
```

A typical result distinguishes protocol confidence:

```json
{
  "outcome": "accepted_unverified",
  "asset_id": "L046",
  "address": 46,
  "operation": "throttle",
  "requested": {"speed": 12, "direction": "forward"},
  "reported": {"speed": 12, "direction": "forward"},
  "physical_feedback": false
}
```

The final field prevents a command-station echo/broadcast being mistaken for
proof that the locomotive physically moved.

### Predecessor code disposition

| Predecessor module | Disposition |
|---|---|
| `serial/framing.py` | Port with tests; simple and reusable |
| `serial/commands.py` | Port selected low-level encoders; keep validation |
| `serial/parser.py` | Extend for identity, output/mode and scoped power; unknown frames remain observable diagnostics |
| `serial/discovery.py` | Rework selection and Linux device coverage; keep metadata reporting |
| `serial/controller.py` | Redesign around one transport scheduler and connection sessions; do not copy queue behavior unchanged |
| `state.py` | Replace optimistic defaults with unknown/stale/report confidence |
| `api/routes.py` | Rebuild around asset IDs, shared roster, CSRF, typed operations and explicit outcomes |
| React frontend | Reimplemented in TypeScript/Vite against MTOS APIs; Flask serves the compiled static bundle |

Known predecessor defects to cover in tests include commands surviving disconnect,
serial errors not completing cleanup, non-atomic checking of the programming lock,
priority writes not cancelling stale throttle commands, connected being reported
before readiness, and optimistic desired values appearing as reported state.

## AccessoryNetwork interface

Proposed application-facing operations:

```python
class AccessoryNetwork(Protocol):
    def status(self) -> AccessoryNetworkStatus: ...
    def nodes(self) -> tuple[NodeStatus, ...]: ...
    def enqueue(
        self,
        asset_id: str,
        operation: str,
        value: str | None,
        expected_revision: int,
    ) -> AccessoryJob: ...
    def get_job(self, command_id: str) -> AccessoryJob: ...
    def cancel(self, command_id: str) -> AccessoryJob: ...
```

The adapter owns MQTT connection/reconnection, node presence/session tracking,
publish/receive validation, acknowledgement correlation, and scheduler wake-up.
Core owns the canonical durable command and system-visible result. `mtos_mc`
owns the execution ledger required for physical deduplication and recovery; both
revalidate the leased asset/configuration revision and fencing token defined by
ADR-009.

### MQTT topic shape

The earlier ADR's logical topic contract remains the starting point:

```text
mtos/v1/nodes/{node_id}/commands
mtos/v1/nodes/{node_id}/events
mtos/v1/nodes/{node_id}/availability
mtos/v1/nodes/{node_id}/status
```

Each node subscribes only to its own command topic. Commands are not retained.
Status may use MQTT last-will/availability behavior, but broker presence alone is
not enough to claim a component action succeeded.

### Command envelope

```json
{
  "schema": "mtos.turnout-command.v1",
  "command_id": "019c...",
  "operation_id": "019d...",
  "sequence": 3,
  "node_id": "N001",
  "boot_id": "a4d31f76",
  "producer_session_id": "producer-session-example",
  "accessory_id": "T012",
  "desired_state": "diverging",
  "configuration_revision": 12,
  "issued_at": "2026-09-14T00:00:00Z",
  "expires_at": "2026-09-14T00:00:10Z"
}
```

The envelope contains logical intent, not a raw PCA9685 or 74HC595 channel. The
owning ESP32 stores the mapping from turnout/signal asset IDs to its local channels.
Commands carry the expected configuration revision; the node rejects a mismatch.

### Acknowledgement and completion

Acknowledgement means the node validated and accepted ownership of a current job:

```json
{
  "schema": "mtos.accessory-event.v1",
  "command_id": "019c...",
  "node_id": "N001",
  "boot_id": "a4d31f76",
  "producer_session_id": "producer-session-example",
  "state": "accepted",
  "at": "2026-09-14T00:00:01Z"
}
```

Completion means firmware finished its configured output sequence:

```json
{
  "schema": "mtos.accessory-event.v1",
  "command_id": "019c...",
  "node_id": "N001",
  "boot_id": "a4d31f76",
  "accessory_id": "T012",
  "state": "completed",
  "producer_session_id": "producer-session-example",
  "reported_state": "diverging",
  "physical_feedback": false,
  "at": "2026-09-14T00:00:02Z"
}
```

Failures use stable reason codes such as `expired`, `unknown_asset`,
`configuration_mismatch`, `unsupported_value`, `busy`, `electrical_fault`, or
`execution_timeout`, plus a bounded human-readable detail.

### Scheduling classes (future extension)

The initial implementation uses one actuator queue with one active job globally,
as specified in the implementation contract. The classes below are extension
concepts, not independently concurrent v1 workers. Buffer flashing stays local.

Initial scheduler classes are concrete rather than generic priorities:

| Class | Initial concurrency | Examples |
|---|---:|---|
| `emergency` | immediate control action | future accessory all-safe request |
| `servo` | 1 globally | turnout straight/diverging |
| `signal` | conservatively 1, review after measurement | aspect transition |
| `machine` | 1 | water tank, later turntable |

FIFO order applies within a class unless cancellation, expiry, or safety changes
it. Version 1 may use one global queue to stay simple; the class is still recorded
so measured power behavior can permit safe concurrency later without changing the
public operation model.

### Concrete output behavior

Turnout:

1. Validate one or two servo components and calibrated targets for `straight` or
   `diverging`; a PECO SL-90 double slip uses two coordinated SG90 servos.
   Execute its servos sequentially under one job reservation; complete only after
   both finish and use a timeout derived from the complete sequence.
2. Enable PCA9685 output and move using the node's safe movement profile.
3. Hold for the configured settling time.
4. Disable PWM to reduce heating and idle current.
5. Report completed target; set `physical_feedback=false` until a sensor exists.

Signal:

1. Validate requested aspect against asset type and component refs.
2. Switch all aspect outputs off.
3. Observe a short break-before-make interval.
4. Switch exactly the requested LED output on.
5. Report the aspect; on a partial failure prefer/report `dark` or `uncertain`.

Machine:

1. Validate the action against that machine type's declared interface.
2. Execute a bounded firmware sequence with timeout and safe output cleanup.
3. Report completed, failed, or uncertain. Do not represent a generic pulse as a
   meaningful `operate` action until the water-tank electrical sequence is known.

## Fake interfaces before hardware

Automated tests use deterministic fakes, never `/dev/*`, Wi-Fi, MQTT hardware, or
live GPIO:

- `FakeDccTransport` scripts input chunks, errors, timeouts, and response order;
- `FakeMqttTransport` records publishes and injects ack/state/status messages;
- a controllable clock drives expiry, stale-node detection, and retry timing;
- a synchronous scheduler runner makes queue tests deterministic;
- temporary SQLite databases exercise revision and restart recovery.

Real adapters are enabled only by explicit configuration. Test configuration must
fail closed if a live device path or production broker is supplied accidentally.

## Open interface decisions before implementation

1. Exact water-tank electrical input and safe action sequence.
2. Turntable mechanism, position model, homing/feedback, and motor driver.
3. Exact node identity/provisioning, Wi-Fi credentials, authentication, and MQTT
   broker TLS policy for the isolated layout LAN.
4. Exact 74HC595 signal output circuit and whether transistor/MOSFET stages are
   needed for the constructed LED wiring and measured aggregate current.
5. The Socket.IO event projection and snapshot shape for accessory jobs; polling
   is diagnostic fallback only.
6. Retention limit for completed jobs/events and manual cleanup policy.
