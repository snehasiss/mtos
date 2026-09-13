# Running asset_manager

Requires Python 3.11+ on macOS or Linux. Runtime dependencies are Flask, Waitress
and Pillow; SQLite is the Python standard-library `sqlite3` module. On older ARM
systems Pillow may require the OS JPEG/zlib development packages to build.

```bash
python3 -m pip install -r requirements.txt
python3 -m pip install -e .
tools/asset_manager start
tools/asset_manager status
tools/asset_manager restart
tools/asset_manager stop
```

`requirements.txt` lists the current runtime dependencies and matches
`pyproject.toml`. Flask installs its supporting packages, including Werkzeug and
Jinja2. SQLite (`sqlite3`) and JSON are supplied by Python; do not install
similarly named pip packages. The editable project install registers MTOS and its
`mtos_backup` command. For tests, additionally install `-e '.[dev]'` (pytest).

Cubietruck3 A20 deployment uses system Python, without a virtual environment.
Install dependencies on the SBC itself; do not copy iMac compiled packages.
Check that the SBC's OS provides Python 3.11+ with working sqlite3 support. Pillow may need
native build dependencies if a compatible ARM wheel is unavailable, as noted
above. Exact OS packages must be checked against the installed SBC distribution.
If pip reports an externally managed Python environment or a permission error,
stop and select the installation method appropriate to that OS; the commands
above are not instructions to override OS package protections. The SBC OS/version
has not yet been confirmed. A virtual environment remains optional for development.
Service launchers use system python3 when no project .venv exists.
After installation, verify:

```bash
python3 -m pip check
python3 -c 'import sqlite3, json, PIL, flask, waitress; print("MTOS dependencies OK")'
```

These version ranges are not a platform-tested lockfile. The current application
has not yet been commissioned on the A20. Serial/MQTT packages are not included
because asset_control is not implemented; add them when that code is introduced.

Default bind: `0.0.0.0:5301` (all IPv4 interfaces). For an iPhone on the same trusted LAN:

```bash
tools/asset_manager start
```

Open `http://<SBC-or-iMac-IP>:5301` on the phone. This release has no user-account
authentication; use a trusted local network. It includes CSRF protection for all
mutations and uses Waitress rather than the Flask development server. Debug mode
is off. PID state and logs are under `data/run/`. Start and restart default to
`0.0.0.0`; pass `--host 127.0.0.1` each time for local-only access. The port is
fixed at 5301. Run service commands as the same OS
user. Graceful stop waits for exit and never force-kills an unrelated process.

## Data and migration

`data/db/mtos.sqlite3` and `data/media/<family>/<asset_id>_n.jpg` are ignored by
Git. `MTOS_DATA_DIR=/path/to/data` configures another root for service and utilities.
Schema version 3 is initialized/upgraded automatically; SQL is in `src/mtos/migrations`.
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

`tools/asset_control (start|stop|restart|status)` reserves port 5302. Start and
restart report that the future control service is not implemented and return
nonzero; they do not launch a placeholder hardware controller.

## Manual backups and restoration

Activate the environment, mount the destination, and invoke:

```bash
tools/mtos_backup --remote ~/gdrive/backup/mtos/data --backup
```

The directory must already exist. `--remote` is a mounted filesystem path, not an
SSH/cloud API. Each invocation creates a new timestamped snapshot; no prior backup
is overwritten or deleted. The tool holds the shared application write lock while
using SQLite online backup and copying media, then verifies checksums and database
integrity before publishing the snapshot. Images and DB metadata are consistent
for all MTOS writes; external direct filesystem/database edits bypass that lock.

```bash
tools/mtos_backup --remote ~/gdrive/backup/mtos/data --verify
tools/asset_manager stop
tools/mtos_backup --remote ~/gdrive/backup/mtos/data --restore
tools/asset_manager start
```

Restore chooses the newest completed snapshot from the supplied directory (or an
explicit snapshot directory). It fails if verification fails; it does not silently
fall back to an older snapshot. Stop services first. Current data is preserved in
a dated sibling directory before verified replacement. To rehearse without replacing
current data, add `--restore-to ~/mtos-restored-data`, which must not exist.
Session secrets regenerate after restore;
logs and PID files are not backed up. No backup job is scheduled. Cron may invoke
the command later when desired; a missing destination makes it exit nonzero.

## JSON API

| Endpoint | Purpose |
| --- | --- |
| GET /api/assets?q=&family=&status=&limit=24&offset=0 | Search/paginate |
| POST /api/assets | Add asset and lifecycle |
| GET /api/assets/L001 | Read composed roster record |
| PATCH /api/assets/L001 | Update fields; revision required |
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
date is `purchased_on`. Physical programming/operation is outside this application.

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
