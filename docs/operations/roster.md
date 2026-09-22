# Running mtos_asset

Requires Python 3.11+ on macOS or Linux. Runtime dependencies are Flask, Waitress
and Pillow; SQLite is the Python standard-library `sqlite3` module. On older ARM
systems Pillow may require the OS JPEG/zlib development packages to build.

```bash
python3 -m pip install -r requirements.txt
python3 -m pip install -e .
tools/mtos_asset start
tools/mtos_asset status
tools/mtos_asset restart
tools/mtos_asset stop
```

`requirements.txt` lists the current runtime dependencies and matches
`pyproject.toml`. Flask installs its supporting packages, including Werkzeug and
Jinja2. SQLite (`sqlite3`) and JSON are supplied by Python; do not install
similarly named pip packages. The editable project install registers MTOS and its
`mtos_backup` command. For tests, additionally install `-e '.[dev]'` (pytest).

Image uploads/imports are limited to 20 MiB compressed input and 25,000,000
decoded pixels. Optimization is serialized with a bounded four-request waiting
queue to prevent several decoded images exhausting a small host.
Treat bulk directory import as a maintenance task; do not run it during live
railroad operation. ADR-008 defines this constrained-host requirement.

Cubietruck A20 deployment uses Debian 13 system Python without a virtual
environment. The dedicated non-login `mtos` account owns the checkout, data and
Python user site; `snehasis` remains the human administrator. Install dependencies
on the SBC itself and never copy iMac-compiled packages. Pillow may need native
build dependencies when an ARMv7 wheel is unavailable. Follow the
[SBC provisioning guide](sbc-provisioning.md) rather than applying these generic
development commands as root. Service launchers use system Python when no
project `.venv` exists.
After installation, verify:

```bash
python3 -m pip check
python3 -c 'import sqlite3, json, PIL, flask, waitress, serial, paho.mqtt.client; print("MTOS dependencies OK")'
```

These version ranges are not a platform-tested lockfile. The current application
has not yet been commissioned on the A20. PySerial supports CSB1 control and
Paho MQTT supports the implemented MC adapter; live MQTT is off by default.

Default bind: `0.0.0.0:5301` (all IPv4 interfaces). For an iPhone on the same trusted LAN:

```bash
tools/mtos_asset start
```

Open `http://<SBC-or-iMac-IP>:5301` on the phone. This release has no user-account
authentication; use a trusted local network. It includes CSRF protection for all
mutations and uses Waitress rather than the Flask development server. Debug mode
is off. PID state and logs are under `data/run/`. Start and restart default to
`0.0.0.0`; pass `--host 127.0.0.1` each time for local-only access. The port is
fixed at 5301. Run service commands as the same OS
user. Graceful stop waits for exit and never force-kills an unrelated process.
`tools/asset_manager` is retained as a compatibility alias; both names use the
same `mtos_asset` lock, PID metadata and process, so they cannot start duplicates.

## Data and migration

`data/db/asset.sqlite3` and `data/media/<family>/<asset_id>_n.jpg` are ignored by
Git. `MTOS_DATA_DIR=/path/to/data` configures another root for service and utilities.
Service-owned persistence uses `asset.sqlite3`, `core.sqlite3`, and
`mc.sqlite3`. DCC and HMI are stateless and have no database. The
backup utility includes Core and MC databases when present; Asset and media are
always required.
Schema version 5 is initialized/upgraded automatically; SQL is in `src/mtos/migrations`.
On first startup after the family-folder change, registered legacy files under
`media/<asset_id>/` are moved to `media/<family>/`. Checksums and conflicting
destinations are validated before any old file is removed. Restart the running
service after upgrading so code and filesystem layout change together.

```bash
python3 tools/import_legacy.py \
  --source ~/project/union-pacific-layout/data \
  --photos ~/project/union-pacific-layout/resources/photos/optimized
python3 tools/import_image.py --source ~/Pictures/train-photos/
```

Both migration and photo imports are repeatable and preserve existing destination
records. Migration copies optimized photos byte-for-byte into canonical asset
paths. New photo imports apply EXIF orientation, center-crop to 16:9, and resize
without upscaling to at most 1280×720. Uploads from the roster use the same
processing and persistence.
If the Python running `tools/import_image.py` lacks Pillow, the utility restarts
using the project's `.venv/bin/python3`, preserving arguments and the working
directory. If dependencies are still unavailable, it reports installation
instructions before accessing roster data; it does not install packages itself.
Directory imports accept `.jpg`, `.jpeg` and `.png` (case-insensitive) and resolve
prototype mark+number or a direct asset ID. All output uses `{asset_id}_n.jpg`;
original files remain unchanged. PNG transparency is rendered on white. Files
with the same resolved asset ID and sequence share one destination regardless of
source extension: an existing image is skipped, not replaced.
The image importer defaults to `data/` under the project root, regardless of the
working directory or `MTOS_DATA_DIR`. Its optional `--data-dir` explicitly
overrides that default; services and other utilities retain their existing
`MTOS_DATA_DIR` behavior.
Ambiguous or unknown filenames are reported. Sources are never modified.

Migration mapping: `intent`/`spotted` → planned, `stored` → received/stored,
deprecated `parked` → sheltered, and MOW `cleaner` → track_cleaner. The confirmed
exceptions are applied directly: L046 → received/active at `test_main_1`; M004 and
L143 → shipped. No receipt date or permanent booster dependency is invented. All source JSON,
including media catalogs, is retained exactly in `legacy_document`; acquisition
source, price and legacy acquired date remain accessible in the roster.

The initial migration imported 159 assets and 110 optimized photos. Reimport
preserves subsequent edits and fresh migration applies the confirmed corrections.

`tools/mtos_hmi (start|stop|restart|status)` operates the browser-facing HMI on
`0.0.0.0:5302`; `tools/asset_control` is a compatibility alias for that same
process. HMI opens no serial hardware and uses Socket.IO to submit typed intent to
Core. Stop the complete MTOS service stack before restore or upgrade operations.

## Backup and restoration

The deployed Cubietruck uses `mtos_admin` to synchronize the complete `data/`
tree—not only the Asset database and photographs—to a separate host with rsync
over SSH-key login. Backup and restore require all application services stopped.
Restore is staged, validates every SQLite database, preserves the current local
tree, and then swaps the verified tree into place. See the
[administration guide](admin.md) for prerequisites and operation.

`tools/mtos_backup` remains a legacy local snapshot utility and is exercised by
its compatibility tests, but it is not the deployed network-continuity path.

## JSON API

| Endpoint | Purpose |
| --- | --- |
| GET /api/assets?q=&family=&status=&limit=24&offset=0 | Search/paginate |
| POST /api/assets | Add asset and lifecycle |
| GET /api/assets/L001 | Read composed roster record |
| PATCH /api/assets/L001 | Update Asset-owned fields; revision required; direct DCC-address edits are inventory-only |
| GET /api/assets/L001/media | Media metadata |
| POST /api/assets/L001/media | Multipart image and sequence; shared optimizer |
| GET /api/assets/L001/media/L001_1.jpg | Read registered image |
| GET/POST /api/consists | List/create ordered groups |
| PATCH /api/consists/K001 | Edit ordered units; revision required |
| GET /api/schema | Family/type and lifecycle vocabulary |

API clients obtain a token from `GET /api/session`, retain its session cookie, and
send `X-CSRF-Token` on writes. Dates are ISO dates. Asset PATCH recursively merges
objects; arrays replace their collection; null clears an optional field. Asset IDs
are immutable. Retirement is a lifecycle update with status `retired`. Lifecycle
defaults are status `unavailable` and location `off_track`; its sole optional
date is `purchased_on`.

Asset owns lifecycle status and permits those edits even when operational holds
exist; changing the operating view invalidates those holds and forces Core to
revalidate. The UI warns when removing an active controlled asset because the
save cannot stop already moving hardware. A direct `control.address` edit is also
allowed with a warning and does not program the decoder. The normal physical
address-change path is the Core/DCC programming workflow in ADR-010.

`GET /api/next-asset-id?family=machine` returns the first available ID in that
family prefix, such as `E001`. Passenger and freight share the C namespace. The
add form refreshes this value when family changes; uniqueness is still checked
when saving in case two clients request the same ID concurrently.

The library header uses the square MTOS locomotive wireframe at a compact 48 px.
Asset status is shown on a lightly bevelled green rectangle. Pagination uses
plain arrow-only controls with accessible names and matching 44 by 44 px dark
green touch targets for iPhone use. Asset photos use a single-column 16:9 gallery.
The mobile form deliberately omits raw component, relation, and attribute JSON;
those records remain preserved during normal edits and can receive a separate
technical interface later.

Existing asset details open in protected **View mode**. Inputs, checkboxes and
pickers cannot change until the operator presses **Edit Asset**. In edit mode the
control becomes **Cancel**, which reloads the persisted Asset rather than keeping
unsaved field values; a successful save also returns to View mode. Add Asset
opens directly in edit mode. A persistent captionless message line reports View,
Edit and Saved state. Photo upload is available only while editing.

Asset retains its light cream/caramel/green palette, but panels, 44 px controls,
2 px borders, 10–12 px bevels and custom dropdowns use the same component language
as HMI. Native selects remain the submitted form controls while the visible picker
prevents platform-specific iOS menu styling from defining the application UI.

## Verification

```bash
python3 -m pytest -q
```

The suite covers domain rules, persistence, failed-write rollback, stale revisions,
CSRF, API CRUD, photo upload/import, migration repeatability, and checksum-verified
backup/restore. Backups cannot replace a separate physical copy: retain snapshots
on another device and periodically perform a restore rehearsal.

An optional browser test exercises add, edit, search and retirement at a 390px
phone viewport. Run it in an environment permitted to launch Chromium:

```bash
python3 -m pip install playwright
python3 -m playwright install chromium
MTOS_BROWSER_TESTS=1 python3 -m pytest tests/test_mobile_ui.py -q
```
