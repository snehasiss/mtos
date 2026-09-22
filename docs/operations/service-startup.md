# Integrated service startup and shutdown

Date: 2026-09-18. Scope: DCC MAIN plus the hardware-free accessory-control path.

On the deployed Cubietruck, the system-managed `mtos_admin` service is available
on port 5300 after boot. Normal operator startup and shutdown use its web
interface. It invokes this same stack coordinator:

```bash
tools/mtos_services start
tools/mtos_services status
tools/mtos_services restart
tools/mtos_services stop
```

The five application services are not individually enabled at boot. See the
[Admin installation and operation guide](admin.md).

The coordinator uses `.venv/bin/python3` when that optional development runtime
exists; otherwise it uses the invoking system Python. Deployment does not
require a virtual environment, but all packages in `requirements.txt` must be
installed for that interpreter.

## Startup sequence

1. `mtos_asset` starts on `0.0.0.0:5301`, applies owned roster migrations and
   exposes the internal operating-locomotive and control-lease contracts.
2. `mtos_dcc` starts on `127.0.0.1:5304`. It owns serial discovery and starts
   disconnected, with MAIN power reported as `unknown`. Startup never opens a
   serial device or restores an earlier throttle or power state; it also cannot
   claim physical de-energization before obtaining device evidence.
3. `mtos_mc` starts on `127.0.0.1:5305`, reconstructs its execution ledger and
   starts broker-offline unless live MQTT is explicitly enabled.
4. `mtos_core` starts on `127.0.0.1:5303`, advances its durable fencing epoch,
   establishes fresh sessions with DCC and MC and begins the two-second heartbeat.
5. The coordinator calls Core start and requires both adapter sessions. Failure at
   any stage stops every service already started.
6. `mtos_hmi` starts last on `0.0.0.0:5302`. A browser receives the current Core
   projection and device state through Socket.IO.

At this point the software stack is ready but the railroad is not energized.
The operator selects the EX-CSB1 serial device in HMI and requests Connect.
DCC opens the device and reports connection/identity state through Core to HMI.
MAIN track power is enabled only by a separate explicit operator command.

## Feedback path

```text
EX-CSB1 -> mtos_dcc -> mtos_core -> mtos_hmi -> browser
browser -> mtos_hmi -> mtos_core -> mtos_dcc -> EX-CSB1
ESP32 -> Mosquitto -> mtos_mc -> mtos_core -> mtos_hmi -> browser
browser -> mtos_hmi -> mtos_core -> mtos_mc -> Mosquitto -> ESP32
```

Browser commands receive an acceptance acknowledgement first. Completion,
failure and fresh device state are separate events. HMI watches the Core
projection locally and pushes only changed snapshots; the browser does not use
the former one-second HTTP polling loop. A disconnected device, stale Core–DCC
session or failed heartbeat is therefore visible to the operator and prevents
ordinary control commands.

## Shutdown and failure behavior

Normal shutdown is reverse dependency order: HMI, Core, MC, DCC, then Asset. Core
loss makes DCC reject ordinary commands and attempt one all-stop if a verified
serial station is still available. This is not proof of physical power removal;
an accessible hardware power-off remains necessary.

Each component can still be started individually for diagnostics with
`tools/mtos_asset`, `tools/mtos_dcc`, `tools/mtos_mc`, `tools/mtos_core`, or `tools/mtos_hmi`.
That is not the normal operating sequence, and starting HMI alone does not make
the control system ready.

## Current boundary

HMI is the common human interface for DCC and microcontroller operations.
Locomotive MAIN control is available; CV programming remains Phase 2.
Turnout, signal and machine controls use the loopback-only `mtos_mc` service.
The host implementation and firmware source exist, but physical operation is not
commissioned. With live MQTT disabled, MC starts in broker-offline mode and HMI
disables every accessory command.
Its finalized scope and startup requirements are documented in
[the mtos_mc low-level design](../architecture/mtos-mc-module.md). MC starts
after DCC and before Core; Core establishes fenced DCC and MC sessions
before HMI starts. Set `MTOS_MQTT_ENABLED=1` only for supervised broker/node tests.
