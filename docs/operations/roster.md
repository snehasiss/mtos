# Running asset_manager

Requires Python 3.11+ on macOS or Linux. Runtime dependencies are Flask, Waitress
and Pillow; SQLite is the Python standard-library `sqlite3` module. On older ARM
systems Pillow may require the OS JPEG/zlib development packages to build.

```bash
python3 -m venv .venv
. .venv/bin/activate
python3 -m pip install -e '.[dev]'
tools/asset_manager start
tools/asset_manager status
tools/asset_manager restart
tools/asset_manager stop
```

Default address: `http://127.0.0.1:5301`. For an iPhone on the same trusted LAN:

```bash
tools/asset_manager start --host 0.0.0.0
```

Open `http://<SBC-or-iMac-IP>:5301` on the phone. This release has no user-account
authentication; use a trusted local network. It includes CSRF protection for all
mutations and uses Waitress rather than the Flask development server. Debug mode
is off. PID state and logs are under `data/run/`. Restart preserves the current
host unless overridden; its port is fixed at 5301. Run service commands as the same OS
user. Graceful stop waits for exit and never force-kills an unrelated process.

## Data and migration

`data/db/mtos.sqlite3` and `data/media/<asset_id>/<asset_id>_n.jpg` are ignored by
Git. `MTOS_DATA_DIR=/path/to/data` configures another root for service and utilities.
Schema version 2 is initialized/upgraded automatically; SQL is in `src/mtos/migrations`.

```bash
python3 tools/import_legacy.py \
  --source ~/project/union-pacific-layout/data \
  --photos ~/project/union-pacific-layout/resources/photos/optimized
python3 tools/import_image.py --source ~/Pictures/train-photos/
```

Both migration and photo imports are repeatable and preserve existing destination
records. Migration copies optimized photos byte-for-byte into canonical asset
paths. New photo imports resize within 1280×720, preserve aspect ratio and apply
EXIF orientation. Uploads from the roster use the same processing and persistence.
JPEG directory imports resolve prototype mark+number or a direct asset ID.
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
| POST /api/assets/L001/media | Multipart image, sequence, view, caption |
| GET /api/assets/L001/media/L001_1.jpg | Read registered image |
| GET/POST /api/consists | List/create ordered groups |
| PATCH /api/consists/K001 | Edit ordered units; revision required |
| GET /api/schema | Family/type and lifecycle vocabulary |

API clients obtain a token from `GET /api/session`, retain its session cookie, and
send `X-CSRF-Token` on writes. Dates are ISO dates. Asset PATCH recursively merges
objects; arrays replace their collection; null clears an optional field. Asset IDs
are immutable. Retirement is a lifecycle update with status `retired` and
`retired_on`. Physical programming/operation is outside this application.

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
