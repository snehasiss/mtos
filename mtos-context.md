# MTOS project context

Last updated: 2026-09-13. Checkpoint: asset-manager implementation completed;
owner reviewing the application on an iPhone. Code baseline: `2ff016b`
(`build asset manager roster service`). The owner reports pushing it to GitHub.
This context-file addition is subsequent to that push and is not committed here.

## How to use and maintain this file

Read this file when resuming work, then inspect current code, ADRs and Git status.
It is a handover and checkpoint record, not a substitute for implementation or
tests. Distinguish implemented behavior, agreed future design, historical design,
and unresolved issues. Update this file at meaningful checkpoints with decisions,
files affected, verification results, limitations and the next authorized work.
Keep useful rationale; replace obsolete current-state statements rather than
accumulating contradictory instructions. Never put credentials in this file.

The owner wants simple, straightforward, intuitive implementation. Do not add
features or abstractions beyond agreed scope. Finish the current change, test it,
fix related failures, and leave a coherent checkpoint. Preserve user edits and
live data. The owner reviews and handles Git commits/pushes; do not commit or
push without an explicit request. Do not launch delegated agents unless asked.

## Product and repository

- MTOS = Model Train Operating System; repository `github.com/snehasiss/mtos`.
- Local project: `/Users/snehasis/project/mtos`.
- Two primary functions: asset management and layout operation. Autonomous
  operation is a third, aspirational function.
- Lightweight, self-hosted, out-of-box model-train software, without requiring
  JMRI, WiThrottle or a heavyweight Java application.
- Python 3.11+, Flask, Waitress, standard-library SQLite, JSON and Pillow.
  An iPhone-first browser UI also serves tablet/desktop users.
- SQLite is authoritative, not a collection of independently edited JSON files.
  JSON remains the API and migration representation; variable attributes use JSON
  columns. No external database server is required.
- Source license: Apache-2.0 (`LICENSE`, `NOTICE`); name policy: `TRADEMARKS.md`.
  This records repository policy, not a claim of registered trademark clearance.
- Predecessor project: `/Users/snehasis/project/union-pacific-layout`, retained as
  source/reference, not the place to implement MTOS. Its app/dcc/slm/chat service
  organization motivated separating inventory and operation from optional AI.

## Current services and features

| Service | Port | Implementation |
| --- | --- | --- |
| `asset_manager` | 5301 | Working Flask/Waitress roster UI and JSON API |
| `asset_control` | 5302 | Reserved launcher only; hardware control is not implemented |

The asset manager currently provides:

- Add a minimally specified asset and enrich it later.
- Search by ID, label, prototype reporting mark, road number, combined mark/number
  or prototype model; filter by family and inventory status; paginated results.
- View/update rolling-stock and stationary-asset records, grouped model,
  prototype, control configuration, components, relations, notes and lifecycle.
- Possession/status/location changes and retirement without deleting identity.
- Ordered consist creation and editing, distinct from permanent dependencies.
- Per-asset image gallery and upload; optimize new images and register metadata.
- Repeatable legacy JSON/photo migration and directory-based image import.
- Manual checksum-verified database-plus-media backup, verification and restore.
- Atomic roster writes, reference validation, rollback and revision conflicts.
- Session-based CSRF protection on writes and health/service identity reporting.

No decoder programming, speed/direction control, track-power control, actual
turnout actuation, signal operation, MQTT producer, ESP32 firmware, route engine,
interlocking or autonomous operation is implemented in this service. Editing
`control` records configuration only; it does not contact hardware.

## Domain model: current inventory contract

Every asset has an immutable uppercase letter plus three digits, e.g. `T012`,
not `T12`. `family` and `type` replace redundant group/power/kind/desc classifiers.
Fields and enumerated values use snake case. `label` is optional; rolling-stock
identity belongs in `prototype.reporting_mark` and `prototype.road_number`.

| Family | Prefix | Types |
| --- | --- | --- |
| loco | L | diesel, turbine, steam, booster |
| mow | M | tamper, mpv, track_cleaner, crane, snowplow |
| passenger | C | coach, balcony, heater_car, power_car, luggage, brakevan |
| freight | C | wagon, tanker, gondola, intermodal, flat_car, reefer, caboose, tender |
| node | N | control_node |
| turnout | T | left, right, wye, crossing, double_slip |
| signal | G | ground_2a, mainline_3a, branchline_2a |
| machine | E | water_tank, turntable |
| building | B | engine_house, chemical_plant, station, warehouse, industry |

Passenger/freight IDs share the globally unique C namespace. G avoids confusion
between S and 5; M is Maintenance of Way. `power_car` includes generator cars;
`intermodal` replaces well_car; `water_tank` does not encode operating/static.
Rolling stock includes self-propelled, powered-but-not-self-propelled and
unpowered equipment, but these are not extra mandatory classification layers.

### Groups and concrete attributes

- Root: `id`, `family`, `type`, `label`, `notes`, `revision`, `created_at`,
  `updated_at`.
- `model` (owned scale model): `scale`, `maker`, `product_number`, `catalog_name`,
  `released_on`.
- `prototype` (real-world 1:1 subject): `maker`, `model`, `reporting_mark`,
  `road_number`, variable `attributes` such as `cab` and `unit`.
- `control`: `dcc`, `node_id`, `address`, `speed_steps`, `sound`,
  `decoder` (`maker`, `model`, `serial_number`), variable `attributes`.
  Decoder/address/speed_steps/sound require `dcc: true`; DCC configuration cannot
  simultaneously reference an accessory node. There is no `address_type` field.
  ADR-008 describes deriving short/long at 127/128, not the earlier suggested 128
  short cutoff; actual protocol behavior remains future control work.
- `components`: ordered integral parts identified by parent-local `ref`, with
  `type`, `desc`, `qty`, optional `connection` (`bus`, `channel`), `values`, `spec`,
  `maker`, `model`, `serial_number`, `installed_on`, `removed_on`.
- `relations`: directional `rel`, target `asset_id`, and `reason`.
- `lifecycle`: separate persisted current record, composed into the asset API.
- `media`: generated `base_url` and ordered `images`, separately persisted.

Servo motors are turnout components, not independently numbered assets. A node
is one integral stationary asset containing its electronics. Wiring is recorded
once in `components`; there is no redundant `outputs` array. A turnout may use
`control: {"node_id":"N001"}` and a servo component with `ref: "actuator"`,
`desc: "sg90"`, `connection: {"bus":"servo","channel":3}` and calibrated
`values: {"normal":310,"reverse":470}`. These numbers are illustrative, not
universal calibration. Signal LED refs are `stop`, `slow`, `go`, with descriptions
`red`, `yellow`, `green`; suffixes such as stop_led/red_smd are unnecessary.

### Lifecycle and location

Possession: `planned | ordered | shipped | sheltered | received`.

Status: `unavailable | stored | active | parked | maintenance | retired`.

Possession is acquisition/custody progression; status is inventory availability
once received. `sheltered` replaces the old possession `parked`. `missed` is
removed. `parked` now means on the layout but not actively operating. `stored`
includes boxed; `active` includes installed; `maintenance` includes repair or
workshop. Retirement is status, not possession. No display or scope field in v1.

Assets not received have explicit status `unavailable`. Location is explicit and
defaults to `off_track`. Active/parked require another known layout location.
The 21 values are:

```text
off_track
main_west_1  main_west_2  main_east_1  main_east_2
main_north_1 main_north_2 main_south_1 main_south_2
yard_west_1  yard_west_2  yard_west_3  yard_west_4
yard_south_1 yard_south_2 yard_south_3 yard_south_4
park_1 park_2 test_main_1 test_prog_1
```

Lifecycle also has optional `purchased_on`, `revision`, `updated_at` and an
`acquisition` object preserving legacy purchasing information. Other milestone
dates are removed and their prior values retained as legacy acquisition metadata.
Asset IDs and records are retained on retirement.

Current confirmed values (read-only checked 2026-09-13):

```json
[
  {"id":"L046","lifecycle":{"possession":"received","status":"active","location":"test_main_1"}},
  {"id":"M004","lifecycle":{"possession":"shipped","status":"unavailable","location":"off_track"}},
  {"id":"L143","lifecycle":{"possession":"shipped","status":"unavailable","location":"off_track"}}
]
```

### Dependencies versus consists

`relations` currently support `requires`, e.g.
`{"rel":"requires","asset_id":"L001","reason":"cab"}` on a booster.
A cab unit can stand alone; a cabless booster cannot be active alone. An active
source requires its targets active and co-located. Active boosters require a
cab-equipped locomotive dependency. Reasons can describe cab, turbine, booster
or aux_tank roles; UP28 cab+turbine+tank motivated multipart support. Do not
invent such relationships while importing incomplete source data.

Consists are separate ordered aggregates, e.g.
`{"id":"K001","label":"SAL consist","units":["L001","L002"]}`.
Units run lead-to-trailing, must exist, must be rolling stock and cannot repeat
within a consist. A consist does not replace a permanent requires relationship.
Nested unit role/orientation objects and operational consist execution are deferred.

## Persistence, API and security

Default database: `data/db/mtos.sqlite3`, schema version 3. `MTOS_DATA_DIR` selects
an alternate data root. Normalized tables: asset, model, prototype, control,
component, relation, lifecycle, media, consist, consist_unit, legacy_document,
layout_location. Control/component payloads retain variable JSON configuration;
searchable identities and links are relational. Foreign keys are enabled on each
connection. Writes use transactions and an application filesystem lock.

Master/lifecycle changes share an aggregate revision. PATCH requires the current
revision; stale edits fail with HTTP 409. Objects merge recursively, arrays
replace, null clears optional values. Restore and running services coordinate
using a separate service-lifetime lock. Direct external edits bypass application
locking; SQLite does not make uncoordinated media changes safe.

| Method/path | Purpose |
| --- | --- |
| GET / | Roster UI |
| GET /health | Service, process and instance health identity |
| GET /api/session | Session cookie and CSRF token |
| GET /api/schema | Families/types, possessions, statuses, locations |
| GET /api/assets?q=&family=&status=&limit=24&offset=0 | Search/paginate |
| POST /api/assets | Add |
| GET /api/assets/{id} | Composed record |
| PATCH /api/assets/{id} | Revision-checked edit/retire |
| GET /api/assets/{id}/media | Image metadata |
| POST /api/assets/{id}/media | Multipart upload with sequence; shared optimizer |
| GET /api/assets/{id}/media/{filename} | Registered image |
| GET/POST /api/consists | List/create |
| PATCH /api/consists/{id} | Revision-checked edit |

API clients retain the session cookie and send `X-CSRF-Token` on mutations.
Waitress is used, debug is off, and uploads are limited to 20 MB. There is no
user-account authentication: expose only on a trusted LAN, not the public Internet.
`data/db/session.key` is local session material, not Git content.

## Photos and import

Canonical path: `data/media/loco/L001_1.jpg`, then L001_2.jpg, etc. No random
directory/global media ID is needed; `(asset_id, sequence)` is the key. The
implemented sequence begins at 1. The earlier `_0.jpg` thumbnail proposal is not
implemented; there is no separately generated thumbnail. Do not imply otherwise.
JSON includes one deployment-generated base_url and image filename, sequence,
width and height. Storage additionally records checksums, byte
counts and timestamps. Binaries are not in SQLite or JSON.

```bash
python3 tools/import_image.py --source ~/Pictures/train-photos/
```

Inputs are `REPORTINGMARKROADNUMBER_n.jpg` or `ASSETID_n.jpg`, n >= 1. Resolve the
former against prototype identity; stationary assets use direct IDs such as
G013_1.jpg. Family/type-only filenames cannot distinguish individual assets and
are not guessed or fanned out. Ambiguous/unknown identities are reported.
Repeated imports preserve existing photos; registered destinations are checked
for consistency. Source files are never modified.

New images are EXIF-oriented, converted to RGB JPEG, fitted within 1280x720
without stretching, cropping or upscaling, and saved optimized/progressive.
Upload and directory import use shared persistence. Already-optimized legacy
photos are copied byte-for-byte instead of recompressed.

## Migration and local data

```bash
python3 tools/import_legacy.py \
  --source ~/project/union-pacific-layout/data \
  --photos ~/project/union-pacific-layout/resources/photos/optimized
```

Read-only inventory at this checkpoint: 159 assets (154 loco, 4 mow, 1 freight),
110 media records, 161 preserved legacy documents. Counts may change during the
owner's application review. Source JSON and its SHA-256 are retained in
legacy_document, including media catalogs and unmapped fields. Acquisition
source, price and legacy acquisition dates remain available; receipt dates are
not invented. Reimport preserves destination edits and reports changed sources.

Legacy mapping includes intent/spotted -> planned; stored -> received/stored;
old parked -> sheltered; cleaner -> track_cleaner. Schema migration preserves
removed values and incompatible locations/statuses in acquisition metadata;
invalid old active locations are not treated as valid layout positions. L046,
M004 and L143 corrections are also applied on fresh legacy import. A local
`data/db/before-lifecycle-v2.sqlite3` safety copy was made before the prior upgrade.

The original project was not changed. Its Challenger sketch was copied to
docs/images and is displayed in the main README.

## Service commands and backups

```bash
python3 -m venv .venv
. .venv/bin/activate
python3 -m pip install -e '.[dev]'
tools/asset_manager start
tools/asset_manager status
tools/asset_manager restart
tools/asset_manager stop
# iPhone on the same trusted network:
tools/asset_manager start --host 0.0.0.0
```

Default bind is 0.0.0.0:5301; use the computer's LAN IP on the phone.
Start/restart use that default even when previous state recorded loopback;
pass --host 127.0.0.1 explicitly each time to restrict access to the host.
PID/instance state and
logs are in data/run. Commands use the project virtual environment when present.
Stop checks service identity and does not force-kill unrelated processes.
asset_control start/restart report unimplemented and return nonzero; stop/status
do not launch a placeholder. No server is started as part of this context task.

Database, media, session secrets and runtime files are ignored by Git. A source
push does NOT back up the roster or photographs. Backup is explicitly manual:

```bash
tools/mtos_backup --remote ~/gdrive/backup/mtos/data --backup
tools/mtos_backup --remote ~/gdrive/backup/mtos/data --verify
tools/asset_manager stop
tools/mtos_backup --remote ~/gdrive/backup/mtos/data --restore
tools/asset_manager start
```

The remote directory must already exist and be mounted; this is a filesystem
path, not a cloud/SSH connector. No automated job is installed because removable
storage may not be present. The owner can later schedule the same CLI with cron.
Each backup is a timestamped snapshot with SQLite online backup, full media copy,
SHA-256 manifest, DB integrity/foreign-key checks and media verification. Earlier
snapshots are not overwritten or pruned. Application writes are coordinated
while the snapshot is captured.

Restore accepts an explicit snapshot or selects the latest completed snapshot;
corruption fails rather than silently choosing an older one. Stop services first.
Old local data is preserved as a dated sibling data.before-restore-* directory.
For a rehearsal, add `--restore-to /path/to/new-directory` (must not exist).
Logs/PID state/session secrets are not backed up; session secrets regenerate.
Keep snapshots on physically separate storage and rehearse restoration.

## Directory layout

```text
mtos/
├── mtos-context.md                  # This living checkpoint/handover
├── README.md                       # Product, setup, sketch, license links
├── LICENSE / NOTICE / TRADEMARKS.md
├── pyproject.toml                  # Dependencies, packaging, pytest, backup CLI
├── requirements.txt                # Runtime install list, aligned with pyproject
├── .gitignore
├── docs/
│   ├── README.md                   # Documentation index
│   ├── decisions/
│   │   ├── ADR-001-product-scope.md
│   │   ├── ADR-002-persistence.md
│   │   ├── ADR-003-domain-data-categories.md
│   │   ├── ADR-004-decentralized-accessory-nodes.md
│   │   ├── ADR-005-accessory-power-distribution.md
│   │   ├── ADR-006-mqtt-accessory-messaging.md
│   │   ├── ADR-007-stationary-assets-control-network-and-power.md
│   │   └── ADR-008-asset-inventory-model.md
│   ├── architecture/
│   │   ├── system-context.md
│   │   └── layout-automation.md
│   ├── domain/vocabulary.md
│   ├── operations/roster.md         # Run, API, migration, backup/restore
│   ├── reviews/layout-automation-review.md
│   └── images/UP3826_Challenger_sketch.png
├── src/mtos/
│   ├── __init__.py
│   ├── app.py                      # Flask factory/routes/security
│   ├── roster.py                   # SQLite repository, validation, media writes
│   ├── image_optimizer.py          # Shared upload/import image optimizer
│   ├── legacy.py                   # Source migration/mapping/preservation
│   ├── backup.py                   # Snapshot, verify, restore, CLI
│   ├── assets/
│   │   ├── __init__.py
│   │   ├── model.py                # Domain types, IDs and vocabulary
│   │   ├── library.py              # Storage-neutral aggregate/reference rules
│   │   └── images.py               # Image identity resolution/directory import
│   ├── migrations/
│   │   ├── 001_roster.sql
│   │   ├── 002_lifecycle.sql
│   │   └── 003-simple-lifecycle.sql
│   ├── templates/roster.html
│   └── static/roster.css, roster.js
├── tools/
│   ├── asset_manager               # start/stop/restart/status, 5301
│   ├── asset_control               # Reserved control launcher, 5302
│   ├── service.py                  # Service lifecycle implementation
│   ├── serve.py                    # Waitress entry and lifetime lock
│   ├── import_image.py
│   ├── import_legacy.py
│   └── mtos_backup
├── tests/
│   ├── test_assets.py
│   ├── test_images.py
│   ├── test_roster.py
│   ├── test_lifecycle_v2.py
│   ├── test_service_bind.py
│   └── test_mobile_ui.py
├── data/                           # Local operational data, not source history
│   ├── db/                         # mtos.sqlite3, session.key, safety copy
│   ├── media/{family}/              # {asset_id}_n.jpg
│   ├── run/                        # Service state, locks and logs
│   └── .lock                       # Application data-write coordination
└── .venv/                          # Local Python environment, ignored
```

Generated caches/egg-info are omitted above and ignored. Optional local backup
directories and service-lifetime locks are also ignored. New clones must migrate,
restore or create their own data; ignored directories are not supplied by Git.

## Future control design: context, not implemented features

SBC-A20/Cubietruck owns deterministic operation and the accessory scheduler.
Axon is strictly for later SLM planning, not a parallel hardware authority. The
direct Cubietruck-to-EX-CSB1 serial locomotive path must not depend on MQTT/Wi-Fi.
Accessory nodes use ESP32 and MQTT over Wi-Fi with Mosquitto on the Cubietruck.

Later owner decisions: one ESP32 CP2102 dual-core 30-pin board, one PCA9685 and
one XL4015 converter per node, 12 V distribution with local 5 V conversion;
roughly 6–10 SG90 turnout actuators and signal LEDs per geographical cluster.
Actuators belong to their turnout assets, while electronics belong to Nxxx.
V1 signals assume raw PCB/SMD LEDs with individually limited current and mutually
exclusive stop/go or stop/slow/go aspects. Mixed commercial signal interfaces
are not required for this version.

Initial planning scope: 20 turnouts, 12 two-aspect ground signals plus 8
three-aspect mainline signals, Broadway Limited water tower and Faller chemical
plant lighting. Other installations/turntables extend the budget later. No
additional 1000 µF servo reservoir was selected; ordinary converter decoupling
remains necessary. Sequencing is not electrical fault protection.

ADR-007 retains a central global one-servo-at-a-time scheduler, not distributed
MQTT token ownership or shared subscriptions. Per-node topics:
`mtos/v1/nodes/{node_id}/{commands,events,availability,status}`. QoS 1 commands
are non-retained. Command/operation IDs, boot_id, configuration_revision,
issued/expiry timestamps and idempotent result caching guard retries/stale work.
Events distinguish accepted, started, completed, failed and rejected; broker ACK
is not physical completion. Without sensors, completion proves output sequence
completion only. A timeout/restart stops the sequence and requires reconciliation,
not automatic movement replay. Signals protect routes before turnout movements.

The recorded initial timeout proposal is 1 s publish ACK, 1 s acceptance (retry
same ID once), 0.5 s accepted-to-started, 2.5 s local servo watchdog and 3 s
producer completion timeout. These have not been commissioned in firmware.

Historical supply allocations in ADR-007: separate 15 V/6 A DCC, 5 V/2 A A20,
12 V/5 A USB-PD Axon and 12 V/5 A accessory supply. The Axon must negotiate PD,
not receive passive voltage on USB-C. The historic accessory calculation was
33.8 W peak / 42.2 W including 25% reserve, with provisional 12 W water-tower
and 2.4 W plant-light allowances. These are documented assumptions, not measured
ratings or a current validated purchasing specification.

## Known discrepancies and boundaries to preserve

1. ADR-008 supersedes ADR-003 for inventory; ADR-007 supersedes ADR-004/005/006
   for its original control consolidation. Older docs are historical, not all
   simultaneous current contracts.
2. ADR-007 still says LM2596 and four nodes/five PCA9685 boards, including one
   two-board node. This conflicts with the later one-PCA9685/XL4015 decision.
   Its 68-channel calculation assumes 20 servo outputs plus 48 individual signal
   aspect outputs; it must not be reused as a validated map for the newer node
   design. Double-slip actuator counts also need a concrete channel map.
3. ADR-008 mentions 74HC595 node components, but no working signal-driver hardware
   is implemented. Do not treat that mention as completed hardware verification.
4. ADR-007 turnout terminology straight/diverging differs from ADR-008 inventory
   calibration normal/reverse. Resolve deliberately before control implementation.
5. Power budgets, resistor values, converter capability, idle/stall behavior,
   branch fuses and native water-tower current still require physical validation.
   This checkpoint does not revise the BOM or give electrical certification.
6. The older storage-neutral model still includes a Media dataclass with a numeric
   id/thumb representation. Live SQLite/API media uses asset_id+sequence and the
   canonical filenames above. Do not copy the older representation into new APIs.
7. No UI claim should exceed verification: automated browser execution was blocked
   by the prior sandbox; the owner is now doing real iPhone review.
8. Do not infer running-process state from this file. The owner reported killing
   old processes; check actual health if service work is requested.

These are recorded for continuity, not authorization to expand this documentation
task into refactoring, hardware design, new UI work or operation implementation.

## Verification and checkpoint history

At the completed implementation checkpoint:

- pytest: **41 passed, 1 skipped** (optional browser test).
- Python compileall passed; Ruff E9/F checks passed; roster.js syntax check passed.
- Git whitespace check passed.
- Fresh migration imported all 159 assets and 110 photos, with the three confirmed
  lifecycle corrections and no reported migration warnings/errors.
- Backup/verify/restore-to rehearsal passed; DB integrity and foreign keys passed.
- Legacy photo copying preserved all 110 source images byte-for-byte.
- Optional 390x844 browser CRUD/search/retirement test exists but Chromium launch
  was denied by the execution sandbox. It is not a passing visual QA result.

Relevant test command: `.venv/bin/python -m pytest -q`. Optional real browser test
requires Playwright/Chromium and `MTOS_BROWSER_TESTS=1`; see the operations guide.
Coverage includes domain rules, stale edits, transaction rollback, references,
consists, API/CSRF, images, legacy reimport, lifecycle migration, backup integrity,
restore locking and reserved control-service behavior.

2026-09-13 context-only checkpoint: inspected tracked source/docs and read-only DB
counts/corrections; created this file. No application logic, live data or running
service was changed; no test-suite rerun was needed for the prose-only addition.
The owner reports the code was pushed and is reviewing on iPhone. Next work is
to receive that review, agree any fixes, implement only that scope, test, and
update this context at the next checkpoint. No additional features are authorized.

### 2026-09-13: Wi-Fi bind-default correction

The owner requested all-interface binding for iPhone access. tools/service.py
and tools/serve.py now default to 0.0.0.0. Restart intentionally does not retain
an old loopback bind; an explicit --host still overrides the default. Health
probes continue using loopback when listening on all interfaces. Startup output
reports the listening address rather than confusing it with the health URL.
asset_control remains reserved/unimplemented, with the shared launcher default.
README and the roster operations guide were updated. test_service_bind.py covers
start, restart from old loopback state, direct server defaults, explicit loopback
override, saved state and health-probe addressing using mocks (no live sockets).

Verification: 47 tests passed, 1 optional browser test skipped; Ruff E9/F and
whitespace checks passed. Attempting to restart existing PID 56120 was denied by
the execution sandbox at SIGTERM. The owner must run tools/asset_manager restart
in their terminal to apply the new binding to that process. No live data was
changed; this change has not been committed or pushed.

### 2026-09-13: asset_control requirements review (no implementation)

Owner requested review/planning based on the working predecessor dcc_service,
especially device awareness and the unresolved MAIN/PROG bench workflow.
See docs/architecture/asset-control-plan.md for findings and phased proposal.
Reviewed predecessor backend, frontend mode handling, config and tests; its
32 tests passed without hardware. CV API tests mock responses, not real decoders.
Missing verified device readiness, per-output mode/power, safe queue recovery and
programming reconciliation prevent treating it as a complete MTOS control design.

Proposed A->test_main_1 plus B->test_prog_1, with B switchable between programming
and running so the locomotive need not move for each CV edit. This is a proposal
requiring wiring/firmware confirmation, not a hardware change or approved ADR.
Native documentation supports role switching; JOIN/PoM are separate later options.
Address writes need a durable pending/verified/committed-or-uncertain workflow:
database transactions cannot atomically roll back decoder hardware.
Next step is owner review of the bench arrangement and the small control contract.
No asset_control code, predecessor files, live data or hardware was modified.

### 2026-09-13: photo-import interpreter fix

Owner's `python3 tools/import_image.py --source ~/Pictures/train-photos/
--data-dir data/` failed with missing PIL. Confirmed system Python lacks Pillow,
while project .venv has Pillow 12.3.0. The importer now checks before constructing
Roster; on missing Pillow it re-executes with project .venv/bin/python3 when not
already in that environment. Arguments/cwd are preserved, so relative data/ works.
If unavailable there too, it exits with setup instructions instead of a traceback
and without opening data. No packages are installed automatically.
Regression tests cover real fallback using a dependency-free base interpreter
and successful temporary-photo import, plus missing-environment failure before
data creation. Verification: 49 passed, 1 optional browser test skipped; Ruff
E9/F and whitespace checks passed. Owner's photos/live data were not imported
or changed by this fix; rerun the original command. No commit or push made.

### 2026-09-13: runtime dependency installation file

Added requirements.txt listing Pillow>=10, Flask>=3.1,<4 and waitress>=3,<4,
matching pyproject.toml. Transitive Flask dependencies are installed by pip;
sqlite3/json are standard library. README and operations guide now show installing
requirements followed by the project itself, optional dev dependencies, and SBC
checks. Python 3.11+ is required. Cubietruck uses system Python without .venv,
as explicitly clarified by the owner; ARM Pillow builds may need OS development libraries.
No speculative serial/MQTT dependencies added. A20 compatibility remains to be
commissioned; requirements are compatible ranges, not a deployment lockfile.

Owner clarification: no .venv on Cubietruck. requirements.txt supports direct
dependency installation; the precise OS-supported installation method remains
dependent on the SBC OS/version. Do not bypass OS package protections by default.
Owner installed Pillow in iMac system Python; image importer uses the current
interpreter when Pillow is available, with project .venv only as a fallback.
README/operations instructions were corrected; no environment was removed or
packages installed by this documentation change.

### Image importer fixed default directory

The importer uses project_root/data when --data-dir is omitted, independently
of the current directory and MTOS_DATA_DIR. --data-dir remains an explicit optional
override. This is specific to tools/import_image.py; service/other utility data
root configuration is unchanged. Regression coverage imports into a temporary
project from another working directory with a conflicting environment variable.

### 2026-09-13: PNG and JPEG input extensions

Directory photo import now accepts .jpg, .jpeg and .png case-insensitively.
Identity/positive sequence naming remains unchanged; output is always canonical
asset_id_n.jpg. PNG transparency becomes white, aspect ratio is preserved, and
originals are untouched. Different extensions resolving to the same asset/sequence
do not overwrite an existing destination. CLI help and operations guide updated.
Tests cover six extension variants through the real CLI, registration, repeat
imports, source preservation, PNG conversion and same-sequence collisions.

### 2026-09-13: family-grouped media storage

Canonical storage is now data/media/{family}/{asset_id}_{sequence}.jpg, for
example data/media/loco/L094_1.jpg and data/media/signal/G013_1.jpg. Family comes
from the authoritative asset row after filename identity resolution; filenames
remain globally distinct. Public API URLs and database filenames do not change.
Import, upload, serving, legacy migration, backup verification, documentation
and tests use the new layout. Roster initialization safely migrates registered
legacy asset directories, validating checksum/collisions and removing only empty
old folders. Old backup manifests remain verifiable/restorable. Asset family
changes are rejected while media is attached to prevent misplaced files.

Implementation checkpoint: all 115 registered live images were moved in place:
113 under data/media/loco and 2 under data/media/mow. Post-migration verification
found 115 registered files, zero missing and zero checksum mismatches; only the
two family directories remain at the first media-directory level. No database
row, filename or public API URL changed. Full suite: 60 passed, 1 optional browser
test skipped; Ruff E9/F, compileall and whitespace checks passed. Tests include
live-layout migration behavior, API serving, family-change rejection and legacy
backup compatibility. No code commit was made.

The asset_manager process PID 57028 was still running code loaded before the
media-path change. Its health was good on 0.0.0.0:5301, but an image request
returned 404 after files moved. Sandbox permissions prevented SIGTERM during the
attempted restart. Owner must run tools/asset_manager restart in their terminal
before UI review; this loads the family resolver and restores image delivery.

### 2026-09-13: compact iPhone UX and explicit lifecycle defaults

Lifecycle schema v3 replaces implicit nulls with status `unavailable` and
location `off_track`. Non-received assets must remain unavailable; active/parked
assets cannot be off_track. Four milestone dates were removed in favor of optional
`purchased_on`. Migration derives it from a complete legacy acquired date and
preserves prior milestone dates as legacy acquisition metadata. It creates
data/db/before-lifecycle-v3.sqlite3 once before upgrading. Media view/caption
columns and UI fields were removed.

Family selection calls GET /api/next-asset-id and read-only auto-populates the
first unused ID for that prefix; machine proposes E001. Passenger and freight
share C allocation. The insert remains the concurrency authority. Card typography
uses the predecessor's Inter/system stack: reporting mark/road number are normal
weight and smaller; identity and lifecycle lines are compact monospace. Mobile
cards, gaps, line height, padding and fieldset margins were reduced. Form groups
use very light caramel brown (#f5eadb), and touch controls remain at least 44px.
Inputs use one column at 520px to prevent overlap.

Image normalization moved to core src/mtos/image_optimizer.py. Directory imports
and HTTP uploads share its EXIF-aware, aspect-preserving, maximum-1280x720 JPEG
path. Detail upload asks only for a file; the UI assigns the next sequence.

Verification for this checkpoint: 60 tests passed and the optional Playwright
browser test was skipped; Ruff E9/F, Python compileall, JavaScript syntax and Git
whitespace checks passed. Tests cover v1-to-v3 migration, safety-copy creation,
explicit defaults, legacy purchase/timeline preservation, ID allocation across
prefixes, removed media fields and shared upload optimization. No commit was made.

Post-restart verification: owner restarted asset_manager and PID 60839 is healthy
on 0.0.0.0:5301. The live database is schema v3; integrity_check is `ok` with zero
foreign-key violations. data/db/before-lifecycle-v3.sqlite3 exists. Current
lifecycle distribution is 1 active at test_main_1, 147 stored off_track, and 11
unavailable off_track. All 115 media records remain; L046_1.jpg returned HTTP 200
through the unchanged API. The next machine ID endpoint returned E001.

### 2026-09-13: freight vocabulary and compact library navigation

Freight inventory now accepts `caboose` and `tender`. `tender` means a separately
inventoried auxiliary tender; a steam locomotive's integral tender remains one of
its components. These values are exposed by `/api/schema`, so the Add Asset type
selector receives them without special UI logic.

The asset status badge again uses a light-green background. Previous/next page
controls contain only left/right arrow symbols, retain accessible labels, and are
exactly 44 by 44 px touch targets. The header now places a 48 px square transparent
wireframe locomotive logo to the left of the stacked MTOS title and caption. The
source reference was `/Users/snehasis/Pictures/train-photos/mtos_logo.png`; the
application asset is `src/mtos/static/mtos-logo-wireframe.png` (256 by 256 PNG).

Verification: the focused domain/API suite passed 32 tests. The full suite passed
60 tests with the optional Playwright browser smoke test skipped. Python compile,
Git whitespace checks, the static logo response, API freight vocabulary, arrow
markup and accessibility labels passed. The host shell has no `node` executable,
so the separate JavaScript syntax command could not run; the unchanged JavaScript
is exercised by the existing tests. Restarting the running asset_manager was
blocked by OS process permissions in the Codex sandbox, so the owner must run
`tools/asset_manager restart` before reviewing this checkpoint. No commit was made.

### 2026-09-13: mobile logo refinement

The project header logo was regenerated from the previous wireframe as a less
detailed mobile variant. The full front-facing locomotive composition and all
depicted components were retained, while the cream/double-outline treatment was
reduced toward thinner, cleaner line work. Two later variants were rejected
because they either embedded a checkerboard instead of real transparency or
drifted back toward heavier outlined bands. The selected replacement remains a
256 by 256 RGBA PNG with a genuine 0–255 alpha channel at
`src/mtos/static/mtos-logo-wireframe.png`. No code or CSS changed and no commit
was made. Restarting asset_manager is not required for this static-file-only
replacement; a browser refresh may need cache bypass if it retains the old PNG.

### 2026-09-13: 16:9 media and final asset-manager mobile cleanup

This checkpoint supersedes the earlier aspect-preserving media statements. The
shared core optimizer now applies EXIF orientation, converts transparency to a
white JPEG background, center-crops every new import or HTTP upload to exact 16:9,
and downsizes without upscaling to a maximum of 1280 by 720. Output dimensions are
integer multiples of 16 by 9; inputs below 16 by 9 pixels are rejected. Existing
media files are not rewritten because the owner confirmed they are already 16:9.
Tests cover wide-image center cropping,
small images, PNG transparency, all supported extensions, CLI imports, and HTTP
uploads.

On mobile library cards, the image uses 16:9 with cover rendering and the adjacent
asset body has reduced vertical padding. Status uses a light-green rectangle with
4 px corner bevel instead of a pill. Pagination now uses plain `←` and `→` glyphs
in matching 44 by 44 px dark-green controls. The detail form constrains the iOS
date input to its grid width, gives the `← Library` button a darker border, and
shows photos as one full-width 16:9 column with slightly rounded corners.

The raw Components, Relations, and Prototype attributes JSON fields were removed
from the asset-management UI. The domain model and API retain these structures;
normal edits preserve existing values rather than clearing them. A technical UI
or CLI can manage them later, but none was added at this checkpoint.

Verification: 62 tests passed and the optional Playwright mobile-browser test was
skipped. Python compilation and Git whitespace checks passed. Restarting the live
asset_manager was blocked by OS process ownership in the Codex sandbox; the owner
must run `tools/asset_manager restart` before testing imports/uploads or reviewing
the uncached UI. No commit was made and no asset_control work was started.
