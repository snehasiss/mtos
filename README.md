# MTOS

**Model Train Operating System**

![Union Pacific Challenger locomotive sketch](docs/images/UP3826_Challenger_sketch.png)

MTOS is a lightweight, open-source platform for managing model-rail assets and
operating a model railway. It is intended to run on modest single-board
computers and provide a browser-based experience without requiring JMRI,
WiThrottle, or another heavyweight desktop application.

## Project intent

MTOS will provide one coherent platform for:

- asset inventory, acquisition, configuration, maintenance, and retirement;
- layout definition, including track, turnouts, signals, and trackside assets;
- command-station integration and safe train control;
- programming locomotives and accessories;
- operating sessions, routes, interlocking, and eventual automation;
- phone, tablet, and desktop access through a lightweight web interface.

MTOS is not tied to a railroad, scale, command station, control protocol, or
host computer. Hardware and protocol integrations are adapters around the MTOS
domain rather than assumptions embedded in it.

## Status

The asset-management application and the Phase 1 DCC control path run on Python,
Flask and SQLite with iPhone-first browser interfaces. `mtos_hmi`, `mtos_core`
and `mtos_dcc` are integrated; real EX-CSB1 commissioning and the future
`mtos_mc` accessory service remain pending.

## Run mtos_asset

```bash
python3 -m pip install -r requirements.txt
python3 -m pip install -e .
tools/mtos_asset start
```

Open `http://127.0.0.1:5301`. Use `tools/mtos_asset restart`, `stop`, or `status` to
manage the service. It binds to `0.0.0.0` by default. For a phone on a trusted LAN,
open the host's LAN IP address on port 5301. Use `--host 127.0.0.1` explicitly
for local-only access. This release has no account authentication.

The database lives in `data/db/`; photos live in `data/media/`. Both are excluded
from Git. Backups are manually invoked to an existing mounted destination:

```bash
tools/mtos_backup --remote ~/gdrive/backup/mtos/data --backup
tools/mtos_backup --remote ~/gdrive/backup/mtos/data --restore
python3 tools/import_image.py --source ~/Pictures/train-photos/
```

See [the roster guide](docs/operations/roster.md) for migration, configuration,
backup verification, restore, and JSON endpoints.

The asset service is `mtos_asset` on port 5301. `tools/asset_manager` remains a
compatibility alias and addresses the same process. The browser service is
`mtos_hmi` on port 5302:

```bash
tools/mtos_services start
```

Open `http://<SBC-or-iMac-IP>:5302`. The service starts disconnected and never
energizes track power automatically. Select the EX-CSB1 USB serial device, connect,
verify readiness, then explicitly enable MAIN power. Stop/restart/status use the
same launcher syntax. Use this only on a trusted local network.

`tools/asset_control` remains a compatibility alias for `mtos_hmi`. The browser
is written in React and TypeScript and compiled by Vite.
Flask serves the committed production bundle, so Node.js is not required on the
Cubietruck at runtime. Frontend developers need Node.js and pnpm; after changing
`frontend/asset_control/`, rebuild the bundle with:

```bash
tools/build_asset_control_ui
```

The generated files under `src/mtos/control_ui/` are part of the application and
must be updated together with their React source.

Current design material is under [`docs/`](docs/README.md).

The stack coordinator starts Asset, DCC and Core, establishes the fenced
Core–DCC session, and starts HMI only after Core is ready. It stops them in the
reverse order:

```bash
tools/mtos_services status
tools/mtos_services restart
tools/mtos_services stop
```

Asset and HMI listen on the trusted LAN. Core and DCC remain loopback-only on
ports 5303 and 5304. HMI uses Socket.IO and calls Core only; Core validates
Asset data and is the sole service allowed to command DCC. See the
[startup and shutdown guide](docs/operations/service-startup.md).

For development/tests, install `python3 -m pip install -e '.[dev]'` as well.
Cubietruck deployment uses system Python 3.11 or newer, without `.venv`.
A development virtual environment is optional. See the roster guide for
deployment checks and OS-managed Python installation constraints.

## License and name

Source code is licensed under the Apache License 2.0. See [`LICENSE`](LICENSE).

MTOS, Model Train Operating System, and future MTOS logos identify the official
project and are not licensed as product names for modified distributions. See
[`TRADEMARKS.md`](TRADEMARKS.md).
