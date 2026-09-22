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
| `mtos_admin` | `0.0.0.0` | 5300 | Authenticated host and stack administration |
| `mtos_asset` | `0.0.0.0` | 5301 | Asset master data and media |
| `mtos_hmi` | `0.0.0.0` | 5302 | Trusted-LAN browser interface |
| `mtos_core` | `127.0.0.1` | 5303 | Canonical operational workflows |
| `mtos_dcc` | `127.0.0.1` | 5304 | Exclusive EX-CSB1 serial adapter |
| `mtos_mc` | `127.0.0.1` | 5305 | MQTT/ESP32 hardware adapter |

Admin, Asset and HMI are reachable from the trusted LAN. Admin is authenticated;
Asset and HMI do not have user-account authentication and must not be exposed to
the Internet or an untrusted network.

### Canonical lifecycle command

Use the checked-in coordinator, not invented Python module entry points:

The deployed `mtos_admin` process invokes `tools/mtos_services` as the dedicated
`mtos` service account. For supervised diagnostics, `snehasis` may invoke the
same coordinator with `sudo -u mtos -H` from `/home/mtos/project/mtos`.

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
- The complete `data/` tree is excluded from Git and is mirrored to a separate
  host by `mtos_admin` as defined by ADR-013.
- DCC and HMI do not receive empty databases merely for naming symmetry.
- Use a non-default, shared `MTOS_INTERNAL_TOKEN` for all five services in a
  deployed stack.
- Live MQTT remains disabled until Mosquitto, credentials, ACLs and ESP32
  commissioning are ready.

### Supervision

ADR-013 supplies one system-level systemd unit for `mtos_admin`; it is the only
MTOS service enabled at boot. The five application services remain under the
existing coordinator and are started explicitly from the Admin interface. They
do not receive independent systemd units that could contradict the coordinator's
dependency order.

The system unit runs as the non-login `mtos` identity. That account owns the
checkout, operational data and Python user site and belongs to `dialout`; it has
no sudo privilege. `snehasis` remains the human SSH/sudo administrator. User
linger and five independent application units are neither required nor used.

## Commissioning sequence

1. Run the automated test suite without hardware:

   ```bash
   sudo -u mtos -H python3 -m pip install --user \
     -e '/home/mtos/project/mtos[dev]'
   sudo -u mtos -H python3 -m pytest -q \
     /home/mtos/project/mtos/tests
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
- Only authenticated Admin starts automatically at boot; the application stack
  starts on explicit operator request in the implemented dependency order.
- The Cubietruck remains a valid non-AI control host, subject to measured latency,
  memory, microSD reliability and hardware commissioning.
