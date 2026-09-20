# ADR-012: Deploying MTOS on Cubietruck A20

- **Status:** Accepted; commissioning pending
- **Date:** 2026-09-20
- **Depends on:** ADR-009 and ADR-011

## Context

MTOS has been checked out on the Cubietruck running Armbian Debian 13 Minimal.
The deployment must preserve the service boundaries, ports, startup fencing and
safe device behavior already implemented in the repository. The Cubietruck uses
a 32 GB microSD card and joins the trusted home LAN over Wi-Fi.

The earlier draft of this ADR assigned Core to port 5302, placed HMI on loopback,
started Core before its adapters and proposed `python3 -m mtos_*` commands. Those
statements do not match the code and must not be used for deployment.

## Decision

### Service placement

| Service | Bind address | Port | Responsibility |
|---|---:|---:|---|
| `mtos_asset` | `0.0.0.0` | 5301 | Asset master data and media |
| `mtos_hmi` | `0.0.0.0` | 5302 | Trusted-LAN browser interface |
| `mtos_core` | `127.0.0.1` | 5303 | Canonical operational workflows |
| `mtos_dcc` | `127.0.0.1` | 5304 | Exclusive EX-CSB1 serial adapter |
| `mtos_mc` | `127.0.0.1` | 5305 | MQTT/ESP32 hardware adapter |

Only Asset and HMI are reachable from the LAN. This version has no account
authentication and must not be exposed to the Internet or an untrusted network.

### Canonical lifecycle command

Use the checked-in coordinator, not invented Python module entry points:

```bash
cd ~/project/mtos
tools/mtos_services start
tools/mtos_services status
tools/mtos_services stop
```

The implemented startup sequence is:

1. Asset
2. DCC (disconnected; it does not open serial or energize track power)
3. MC (broker-offline unless `MTOS_MQTT_ENABLED=1`)
4. Core
5. Core establishes fresh fenced sessions with DCC and MC
6. HMI

Shutdown uses the reverse order. If startup or Core initialization fails, the
coordinator stops services already started. The detailed contract remains in
`docs/operations/service-startup.md`.

### Data and configuration

- `data/db/asset.sqlite3`, `core.sqlite3` and `mc.sqlite3` are operational data.
- `data/media/` contains asset images.
- These paths are excluded from Git and require manual `mtos_backup` backups.
- DCC and HMI do not receive empty databases merely for naming symmetry.
- Use a non-default, shared `MTOS_INTERNAL_TOKEN` for all five services in a
  deployed stack.
- Live MQTT remains disabled until Mosquitto, credentials, ACLs and ESP32
  commissioning are ready.

### Supervision

User-level systemd with linger is an acceptable eventual deployment mechanism,
but it is not yet supplied or tested by this repository. Five independent units
must not encode a dependency graph that contradicts the coordinator. The current
launchers also daemonize child processes and maintain their own PID files, so a
naive `Type=simple` unit around them would not provide correct process
supervision.

Therefore initial Cubietruck testing uses `tools/mtos_services` interactively.
Systemd units will be added only with repository-owned tests for startup order,
environment propagation, restart behavior, logging and clean shutdown. Enabling
user linger is deferred until those units exist.

## Commissioning sequence

1. Run the automated test suite without hardware:

   ```bash
   python3 -m pip install --user -e '.[dev]'
   python3 -m pytest -q
   ```

2. Start the stack and confirm all five health/status results.
3. Review Asset on port 5301 and HMI on port 5302 from the iPhone over the trusted
   LAN.
4. Connect EX-CSB1 from HMI, verify identity/output feedback, and only then enable
   MAIN power for a supervised low-speed locomotive test.
5. Keep address/CV programming off the physical locomotive until the Programming
   HMI and supervised PROG commissioning described by ADR-010 are complete.
6. Keep MC physical actions disabled until Mosquitto and ESP32 hardware are
   commissioned.

## Consequences

- Deployment follows the same startup, fencing and safety path exercised by the
  integration tests.
- A service cannot accidentally expose Core, DCC or MC to the LAN.
- Automatic boot startup is postponed rather than documented with incorrect
  units that could hide failures or violate dependency order.
- The Cubietruck remains a valid non-AI control host, subject to measured latency,
  memory, microSD reliability and hardware commissioning.
