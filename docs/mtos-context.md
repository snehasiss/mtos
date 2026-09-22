# MTOS project context

Last updated: 2026-09-22. Checkpoint: Asset, DCC MAIN, Core, HMI and the
hardware-free MC path are implemented locally. A dedicated authenticated Admin
service and remote SSH/rsync continuity path have also been implemented locally.
EX-CSB1 and accessory electronics commissioning remain pending. The owner
handles commits and pushes.

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
- Python 3.11+, Flask, Waitress for ordinary HTTP services, Flask-SocketIO/
  simple-websocket for HMI, standard-library SQLite, JSON, Pillow, PySerial and
  Paho MQTT. An iPhone-first browser UI also serves tablet/desktop users.
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
| `mtos_admin` | 5300 LAN | Boot-time administration, stack control, remote data backup/restore and Git update |
| `mtos_asset` | 5301 LAN | Roster UI/API and asset configuration authority; `asset_manager` is an alias |
| `mtos_hmi` | 5302 LAN | React/Socket.IO interface for DCC and stationary assets; `asset_control` is an alias |
| `mtos_core` | 5303 loopback | Canonical operational authority and `core.sqlite3` owner |
| `mtos_dcc` | 5304 loopback | Exclusive EX-CSB1 serial adapter |
| `mtos_mc` | 5305 loopback | MQTT/accessory scheduler and `mc.sqlite3` owner |

`mtos_admin` is the only MTOS service enabled through systemd at host boot. It
starts, stops and restarts the other five services through the existing stack
coordinator. Its pale-orange mobile UI uses the MTOS logo and requires an
installation token. Backup and restore accept only
`user@host:/absolute/path`, use non-interactive SSH-key authentication and rsync
the complete local `data/` tree to `<remote>/data/`. These operations and Git
update require the application stack stopped. Restore is staged, verifies all
SQLite databases, preserves the prior local data tree, and acquires the
exclusive service-lifetime lock before swapping. ADR-013 and
`docs/operations/admin.md` are authoritative for setup and operation.

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

The Asset service itself performs no decoder programming, speed/direction,
track-power or accessory actuation. DCC MAIN control is implemented through HMI,
Core and DCC. The MC host path and ESP32 firmware source are implemented but not
physically commissioned. CV/PROG, route/occupancy/interlocking and autonomous
operation remain unimplemented. Editing Asset `control` records never contacts
hardware.

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
`values: {"straight":310,"diverging":470}`. These numbers are illustrative, not
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

Default database: `data/db/asset.sqlite3`, schema version 3 at that checkpoint. `MTOS_DATA_DIR` selects
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
push does NOT back up the roster or photographs. This older checkpoint used
`tools/mtos_backup` with a mounted directory. ADR-013 supersedes it for the
deployed Cubietruck with complete-`data/` rsync over SSH through `mtos_admin`.
The old utility remains only as a compatible local snapshot tool. Earlier
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
├── README.md / mtos-context.md / LICENSE / NOTICE / TRADEMARKS.md
├── pyproject.toml / requirements.txt
├── docs/
│   ├── README.md                    # Current/historical documentation index
│   ├── decisions/ADR-001…ADR-009
│   ├── architecture/                # Service, module and historical designs
│   ├── operations/                  # Roster and integrated startup guides
│   ├── domain/ / reviews/ / mockups/
│   └── images/                      # Schematics and README artwork
├── frontend/asset_control/          # React/TypeScript HMI source and Vite config
├── firmware/esp32_node/             # PlatformIO ESP32 source/config examples
├── deploy/systemd/mtos-admin.service # Boot-time Admin unit template
├── src/mtos/
│   ├── admin_app.py / admin/         # Authenticated host administration
│   ├── asset_app.py / app.py / roster.py / assets/
│   ├── core_app.py / core/          # Operational authority and Core client/API
│   ├── dcc_app.py / dcc/            # EX-CSB1 adapter
│   ├── mc_app.py / mc/              # MQTT/accessory adapter and scheduler
│   ├── hmi_app.py / hmi/            # Socket.IO browser gateway
│   ├── control_app.py / control/     # Superseded monolithic compatibility code
│   ├── control_ui/                   # Committed Vite production bundle
│   ├── migrations/001…005
│   ├── image_optimizer.py / legacy.py / backup.py
│   ├── templates/ / static/
│   └── __init__.py
├── tools/
│   ├── mtos_admin                    # Manual Admin launcher/diagnostics
│   ├── mtos_asset / mtos_hmi / mtos_core / mtos_dcc / mtos_mc
│   ├── mtos_services               # Integrated start/stop/restart/status
│   ├── asset_manager / asset_control  # Compatibility aliases
│   ├── service.py / serve.py / build_asset_control_ui
│   └── import_image.py / import_legacy.py / mtos_backup
├── tests/                           # Admin, Asset, DCC, Core, HMI, MC and integration tests
├── data/                           # Local operational data, not source history
│   ├── db/                         # asset.sqlite3, core.sqlite3, mc.sqlite3
│   ├── media/{family}/             # {asset_id}_n.jpg
│   ├── run/                        # Service state, locks and logs
│   └── .lock                       # Application data-write coordination
└── .venv/                          # Local Python environment, ignored
```

Generated caches/egg-info are omitted above and ignored. Optional local backup
directories and service-lifetime locks are also ignored. New clones must migrate,
restore or create their own data; ignored directories are not supplied by Git.

## Historical accessory-control planning checkpoint

This section records the plan before ADR-009 decomposition and MC implementation.
Current service ownership and implementation status are in the later checkpoints.

The original plan placed deterministic operation and the accessory scheduler on
SBC-A20/Cubietruck and reserved Axon for SLM planning. ADR-009 subsequently made
the control host hardware-independent while retaining one Core authority. The
direct control-host-to-EX-CSB1 path must not depend on MQTT/Wi-Fi; accessory
nodes use ESP32 and MQTT over Wi-Fi with local Mosquitto.

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
2. ADR-007 was revised on 2026-09-14 for one PCA9685 and one XL4015 per node.
   PCA9685 channels are servo-only; signal aspects use 74HC595 outputs. Its
   earlier combined 68-channel PCA9685 calculation is historical and must not be
   reused. Double-slip turnouts consume two coordinated servo channels.
3. ADR-008 mentions 74HC595 node components, but no working signal-driver hardware
   is implemented. Do not treat that mention as completed hardware verification.
4. Turnout state and calibration keys are now consistently `straight` and
   `diverging`; `normal` and `reverse` are not MTOS v1 domain values.
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

### 2026-09-14: asset_control pre-design checkpoint

The owner authorized planning and review only, followed by a pause for manual
review/commit. No control code, migration, UI, device connection, MQTT publish,
serial write, CV operation, or physical command was created or executed.

The current control scope has two independent control points in one Flask service
on `0.0.0.0:5302`: synchronous/bounded EX-CSB1 MAIN locomotive control over USB
serial, and asynchronous durable/queued stationary control through ESP32 nodes
over MQTT. Both consume authoritative asset/configuration data from the existing
`data/db/asset.sqlite3`; no second roster or JSON store is allowed. The Cubietruck
is the sole producer/scheduler. Axon remains reserved for later SLM/autonomy.

The initial operations are direct low-level asset commands: CSB1 readiness/power,
locomotive throttle/direction/functions/stop/emergency-stop; turnout servo state;
mutually exclusive signal aspect; and a defined machine action when its electrical
interface exists. Routes, blocks, interlocking, occupancy, dispatching, and
autonomy are later high-level consumers and are excluded now.

MAIN/PROG role switching and CV programming are explicitly parked. The physical
state remains one test track on CSB1 MAIN; the second isolated track cannot yet be
wired because connectors are unavailable. This limitation does not block the MAIN
or ESP32 foundations.

The predecessor `/Users/snehasis/project/union-pacific-layout/src/csb1` was
reviewed. Reusable concepts are DCC-EX framing/encoding, discovery metadata,
selected parsers, roster-driven selection, and mobile UX. Its controller must not
be copied unchanged: an open port is treated as connected before handshake, queued
commands can survive disconnect, serial-error cleanup is incomplete, request
locking is not an atomic scheduler, priority writes do not cancel stale commands,
and desired values are presented optimistically as state. Its CV tests use mocked
responses, not commissioned hardware. Legacy ESP32 directories are placeholders.

New review documents:

- `docs/architecture/asset-control-pre-design.md`: objective, boundaries, two
  execution models, eligibility, state vocabulary, low-level operations, safety,
  parked scope, knowns/unknowns, UI direction, and staged implementation plan.
- `docs/architecture/asset-control-device-interfaces.md`: typed synchronous DCC
  and asynchronous accessory interfaces, predecessor disposition, exact ADR-007
  MQTT topics/envelope basis, acknowledgement/completion meaning, scheduling,
  output behavior, fake transports, and unresolved device decisions.
- `docs/architecture/asset-control-plan.md`: retained as the detailed predecessor
  DCC/MAIN-PROG review and linked to the new controlling pre-design.

Accepted ADR-007 MQTT specifics remain the baseline: MQTT 3.1.1 compatibility,
Mosquitto/Paho, QoS 1 non-retained commands, plural node topics, retained
availability/LWT, per-boot `boot_id`, `command_id`, configuration revision,
expiry, duplicate-result caching, and producer-side capacity one for turnout
servos. Turnout state and calibration now use `straight/diverging` consistently;
the earlier `normal/reverse` proposal is superseded.

The next authorized phase, after owner review and commit, is implementation in
safe increments with fake devices first. Automated tests must never contact live
serial/MQTT/GPIO. Hardware commissioning remains separately supervised. The later
implementation checkpoint is expected to add accepted ADRs and an SVG internal
connection schematic. No commit was made by Codex.

### 2026-09-14: stationary-control hardware decision refinement

ADR-007 was revised before control implementation. An accessory node is one
ESP32 with one PCA9685 dedicated exclusively to SG90 servo PWM, one XL4015 for
local 12 V-to-5 V conversion, and one or more cascaded 74HC595 shift registers
for mutually exclusive signal aspects. The ESP32 firmware stores the versioned
logical mapping from turnout assets to PCA9685 channels and from signal aspects
to 74HC595 output bits. MQTT commands identify assets and requested states; they
do not expose physical channel numbers.

Turnout states are exactly `straight | diverging`. This applies to single- and
multi-actuator turnouts. A PECO SL-90 Code 100 double-slip is one turnout asset
whose transition coordinates two SG90 components and therefore consumes two
PCA9685 channels; partial movement is a failed operation requiring
reconciliation. `normal | reverse` is not v1 terminology.

The 20-turnout actuator count remains a planning input, not a guaranteed total:
each double-slip adds one servo beyond the one-servo-per-turnout baseline. Four
PCA9685 boards provide 64 servo channels. The specified 12 two-aspect and eight
three-aspect signals require 48 independent aspect outputs. Six 74HC595 devices
are the electrical minimum; fitting two per each of four nodes provides 64
outputs and 16 spare. Exact signal current-limiting/driver circuitry remains a
hardware commissioning decision and must respect both per-output and total
shift-register current limits.

The vector connection drawing is `docs/images/asset-control-connections.svg`.
It covers the Cubietruck/EX-CSB1 DCC path and the complete accessory path:
Cubietruck scheduler and Mosquitto, Wi-Fi/MQTT, ESP32 mapping, fused 12 V branch,
XL4015, PCA9685/SG90 turnout actuation, 74HC595 signal outputs, machine driver,
and node grounding. The architecture and device-interface documents link to it.

This remains a documentation-only checkpoint. No asset_control implementation,
device command, database migration, commit, or push was performed. The blank
item 3 and malformed item 6 in the owner's source list were deliberately not
interpreted as requirements.

### 2026-09-15: asset library card information hierarchy

The asset-manager library card was refined from an iPhone screenshot. The
status badge now occupies the upper-right of the information area, top-aligned
with reporting mark and road number. Asset ID, family and type remain the compact
monospace middle row. Prototype builder and model now form the bottom row when
available. The card body stretches to the image height on mobile so the builder
row stays anchored at the bottom without increasing card height. This was a
presentation-only change; asset data, API payloads and lifecycle semantics did
not change. No commit or push was performed.

After iPhone review, the flexible card space was moved above the classification
and builder rows so those two rows stay together at the bottom. Only the asset ID
uses fixed-width text; family and type now use the same normal UI font as the
prototype builder and model. Desktop card behavior remains consistent.

### 2026-09-17: asset_control design review checkpoint

The controlling refinement is docs/architecture/asset-control-implementation-contract.md.
It supplements ADR-007, the pre-design and device-interface plan; implementation
has not started. Scope remains one asset_control service on 0.0.0.0:5302, shared
SQLite, dedicated EX-CSB1 serial and ESP32/MQTT accessory paths on Cubietruck.

Review decisions: canonical accepted/started/completed node events; MAIN-scoped
power; separate stop eligibility; emergency-stop generations to reject delayed
throttle requests; transactional reservations respected by both services for
control-relevant edits; fresh node readiness and installed configuration; explicit
producer-session handshake and expiry/deduplication rules. WAL needs enabling in
implementation, not merely assuming it is already configured.

Double-slips execute two SG90s sequentially within one reserved job. Timeouts
derive from the whole movement; uncertain execution blocks further actuator
dispatch until reconciled. Configuration provisioning is explicit while idle.
Single-owner firmware maintains the 74HC595 output image and non-blocking timers.

Chemical-plant control is deferred. PECO SL-40 buffer stops each have one red LED
with its own resistor and 74HC595 output; proposed local flash is 500 ms on/off,
continuing through network/SBC loss while the node functions. No 555 in the
baseline. Buffer quantity, inventory family/type/prefix and final circuit remain
open. Signal allocations leave 16 aggregate outputs on eight registers, subject
to per-node distribution. Power/BOM now account for extra double-slip servos and
pending buffer/servo-idle loads; 12 V/5 A is still provisional.

Implementation order: complete DCC MAIN/API/mobile increment with fakes first;
then one complete accessory node/firmware before scaling out; then water tank
after its trigger is defined. CV/role switching, routes and autonomy stay parked.
The SVG remains a component overview, with separate MAIN/PROG paths and buffer
indicators; pin-level assembly details are explicitly pending. Documentation only;
no device commands, code implementation, commit or push.

### Phase sequence and MAIN UI mockup

Owner reordered implementation into three checkpoints: (1) CSB1 MAIN locomotive
control and UI; (2) PROG CV programming within the same UI; (3) stationary turnout,
signal and water-tank control, with local buffer indicators. This supersedes the
earlier accessory-before-CV sequence. Physical PROG commissioning is still pending.

The predecessor React UI and stylesheet were reviewed for visual continuity.
docs/mockups/asset-control-main.html is an interactive standalone proposal using
the predecessor's dark-green/amber palette and system font stack. It has mobile
and desktop layouts, sample roster choices, MAIN power, throttle, direction,
functions and emergency-stop preview states. It connects to no hardware or API.
Visual review precedes production implementation; no commit or push was made.

MAIN mockup review: 48 px red triangular emergency button with white exclamation
mark; Operation/disabled Programming navigation before roster selection; Reverse
left and Forward right; 16 functions per page with previous/next triangles (last
page F64–F68). Removed explanatory panel text and moved demo scenarios into
collapsed settings. Location removed from throttle because inventory location
is manually maintained and no live block detection exists. Essential disabled
and emergency messages remain. This is still only the standalone UI mockup.

### CSB1 MAIN low-level design checkpoint

docs/architecture/asset-control-phase-1-low-level-design.md now specifies Phase 1
file structure, dataclass fields, methods, API bodies, schema-v4 command journal
and reservations, session/generation rules, thread ownership, bounded serial
scheduling, eligibility and roster-edit coordination. Includes configuration
defaults, migration/service integration, separate browser cookie name, compact
UI state/paging rules and automated/supervised acceptance matrices. Phase 2 PROG
and Phase 3 accessories are explicit subsequent checkpoints. Tests are specified,
not yet implemented or executed. No production device code changed.

The mockup was reopened using a version query to bypass stale file-preview cache;
the app reported the browser-open request queued, so refresh success is not verified.

Latest mock review: function buttons are square with bevels; control and widget
borders are stronger; mode-tab type is smaller and the tab row can later extend
to Turnout and Signal. EX-CSB1 is explicitly the sole USB/serial device and owns
its connection/MAIN-power panel. Future ESP32 views reuse the visual shell but
show Wi-Fi/MQTT node status instead. The 48 px emergency triangle has rounded
corners, a red outer outline, white separation and red inner face.

### 2026-09-17: Phase 1 CSB1 MAIN implementation

Phase 1 production code is now present. `asset_control` runs through Flask and
Waitress on 0.0.0.0:5302 using `tools/asset_control`. Startup is de-energized:
it opens no serial port and reports disconnected/MAIN unknown until the operator
selects and connects a candidate USB serial device. The live process was started
as PID 1754 for owner review; its health and control-state endpoints responded.
No serial candidate was opened and no hardware command was sent.

Implementation lives under `src/mtos/control`, `control_app.py`, control.html,
control.css and control.js. It provides DCC-EX framing/validation/parsing, filtered
USB serial discovery, verified identity/TrackManager handshake, continuous reader,
independent emergency write path, MAIN-scoped power, roster-driven throttle and
F0–F68 functions, stop/emergency generation handling and explicit resume. The UI
uses the reviewed compact mobile design and shared asset data; Programming remains
disabled for Phase 2.

Schema v4 adds bounded command-journal/reservation foundations and enables WAL.
Asset-manager writes reject control-relevant changes to reserved assets while
allowing descriptive edits. Dependencies now include pyserial 3.5; it was installed
in the iMac development venv and loaded successfully. Cubietruck may install the
same requirements into system Python without a venv.

Automated tests use fake serial hardware and temporary databases. They cover
protocol framing/validation, identity/output handshake, scoped power, throttle,
emergency, reservation/edit protection, API/CSRF, schema v4 and WAL. The complete
suite now passes 68 tests with one optional browser test skipped. Compilation and
whitespace checks pass. Real CSB1 MAIN commissioning is still pending and must be
supervised. No commit or push was made.

The connected USB serial adapter appeared as `/dev/cu.usbserial-1440` (VID 6790,
PID 29987). A UI connection attempt in the Codex-launched process failed with OS
permission error before the port opened; therefore no identity query, power,
throttle or other DCC frame was sent. The runtime displayed this error safely.
Codex could not restart PID 1754 because the process sandbox denied SIGTERM. That
process still serves health on 5302 but predates the final continuous-reader and
USB-filter refinements. Owner must run `tools/asset_control restart` in Terminal
before commissioning/review. The new process will show only likely USB devices.

### 2026-09-17: Phase 1 mobile control refinement

The production control UI now uses themed in-page listboxes for both EX-CSB1
device and active-locomotive selection instead of native iOS select controls.
The roster endpoint intentionally returns only received, active locomotives with
valid DCC configuration. The redundant Throttle-side MAIN label and routine
connection/power instruction text were removed; disabled controls still show
availability, while emergency-latch guidance remains visible.

Function pages use 4-by-4 keyboard layouts with spaced, bevelled square keys.
The polling renderer preserves each key DOM element so an iPhone touch cannot be
interrupted by the one-second refresh; a press updates immediately and is then
reconciled with the API result. DCC-EX locomotive reports expose only F0–F15, so
the device snapshot now stores reported functions separately from the last
successfully transmitted desired F0–F68 state. Key highlight represents that
commanded state and no longer disappears on pages F16 onward. Mobile padding,
panel gaps, throttle sizing and empty-error space were reduced so Active
locomotive, Throttle and Functions fit more compactly. After review the function
pad returned to a more realistic 4-by-4 arrangement; further widget regrouping
and one-viewport optimization are deliberately deferred until Programming,
Signal, Turnout and Trackside views exist.

The keyboard presentation was subsequently copied from the working predecessor
`union-pacific-layout/src/csb1/frontend`: four columns, 7 px gaps, 56 px minimum
key height, dark key faces, amber active state, prominent function number and a
smaller Headlight/Bell/Horn/Sound label. MTOS retains its five-page F0–F68
navigation and persistent-key touch fix.

Live iPhone review then exposed poor acknowledgement during device operations.
The Waitress log showed requests queuing while Connect/Power/Disconnect calls
were in flight and browser polling continued. The UI now acknowledges touches
immediately with Connecting, Disconnecting, Powering ON or Powering OFF states,
suspends polling during the lifecycle request, prevents conflicting presses and
does not erase errors on the next poll. Function keys change color immediately,
remain fully visible while pending, reject duplicate touches, and reconcile or
roll back after the API result. Their increased-padding shape is enforced as a
perfect square while retaining the predecessor bevel and two-line labels.

### 2026-09-18: asset_control React migration

The asset_control UI was migrated from a Flask template plus imperative JavaScript
to React 19, TypeScript 7 and Vite 8, following the proven predecessor structure.
Source lives in `frontend/asset_control`; Vite emits the committed production
bundle into `src/mtos/control_ui`. Flask serves the hashed bundle and retains all
device, roster, CSRF and control APIs. The Cubietruck runs only Flask/Waitress and
does not require a Node process. Node.js and pnpm are build-time dependencies.

The React state model owns lifecycle feedback, polling, selected locomotive,
throttle debounce, direction, five F0–F68 pages, optimistic function state and
rollback. Polling pauses for device/power and function operations so an old
snapshot cannot erase touch feedback. The UI retains the reviewed theme, custom
device/roster listboxes, emergency stop, 4-by-4 square function keyboard and the
disabled Programming checkpoint. `tools/build_asset_control_ui` installs the
locked dependencies and rebuilds the production assets. The legacy
`templates/control.html`, `static/control.js` and `static/control.css` were
removed.

### 2026-09-18: real-time control architecture redesign

`docs/architecture/control-service-architecture.md` supersedes the temporary
HTTP-polling UI topology. React will use Socket.IO/WebSocket for acknowledged
commands, snapshots and pushed CSB1 events. HTTP remains for health, static
assets and diagnostic compatibility. Waitress cannot remain the asset_control
server after implementation; a supported WebSocket-capable single-worker runtime
must be selected and tested.

The first redesign identified asset management, human interface, operational
Core, CSB1 control and ESP32 control boundaries. The accepted ADR subsequently
formalized six independently supervised services by adding the optional
`mtos_ai` producer: `mtos_asset`, `mtos_hmi`, `mtos_core`, `mtos_dcc`,
`mtos_mc` and `mtos_ai`; Mosquitto remains separate.

The asset interface is the sole command authority: it maps asset IDs, validates
configuration, arbitrates producers, reserves resources and later enforces
occupancy/interlocking. Human UI, schedules and Axon-hosted SLM autonomy are
command producers. SLM may bypass the human interface but never this deterministic
safety boundary or typed hardware adapters. MQTT is only between the ESP32
control adapter and nodes; browsers never publish directly. This checkpoint is
documentation only; WebSocket implementation and hardware commissioning remain
next work.

Owner accepted the separated-service direction and named the services:
`mtos_asset`, `mtos_hmi`, `mtos_core`, `mtos_dcc`, `mtos_mc` and
`mtos_ai`. Core is the central nervous system and sole operational authority;
DCC and MC are hardware-abstraction services. Asset and HMI bind to the trusted
LAN on ports 5301 and 5302. Core, DCC and MC default to loopback ports 5303,
5304 and 5305; co-hosted AI uses 5306. A future AI running on another Axon must
use an authenticated allowlisted ingress or secure tunnel, not public exposure
of all Core interfaces. The services remain in one monorepo with shared typed
protocol packages but independently supervised processes and explicit data
ownership.

ADR-009, `docs/decisions/ADR-009-service-decomposition-and-control-architecture.md`,
formally records this decision. It covers authority, endpoints, WebSocket HMI,
DCC and microcontroller abstraction, MQTT scope, AI restrictions, data ownership,
supervision, alternatives, consequences and migration order. The existing
`docs/architecture/control-service-architecture.md` is its detailed companion.

### 2026-09-18: independent design review incorporated

The review in `docs/mtos-review-design-2026-09-18.md` supports the six-service
boundary but identified four contracts that could not remain implicit. ADR-009
now specifies an Asset-owned multi-asset lease with monotonic fencing tokens,
10-second renewal and 30-second expiry; expired leases require reconciliation
before protected edits. DCC and MC reject stale Core sessions/tokens.

Core heartbeats adapters every two seconds and is stale after six. On Core loss,
DCC rejects normal commands, removes unsent motion and attempts one DCC-EX
all-stop without claiming that power was removed; MC starts no new jobs. HMI has
an authenticated emergency-stop-only bypass to DCC, while physical power removal
remains mandatory for host/link failure. Core owns the canonical operational
command; MC owns a durable execution ledger and deduplication evidence. Lost
acknowledgements are queried and reconciled, never blindly replayed.

ADR-009 also fixes Version 1 limits for browser sessions, unacknowledged commands,
WebSocket messages/backlogs, Core/DCC/MC queues, MQTT inflight messages, replay
windows and terminal history. Pending/uncertain records are never pruned to meet
those limits. Its platform section treats a 2 GiB non-AI host as plausible but
unverified, gives per-process planning ranges, and requires representative soak
measurement before declaring hardware supported. AI has a separate resource
budget.

ADR-008 and roster operations now bound media processing to 20 MiB compressed,
25 million decoded pixels, one optimizer and a four-request queue. Bulk import is
a maintenance operation, not a live-operation workload. These are design
requirements for later enforcement; this documentation checkpoint did not alter
the current optimizer implementation.

The pre-design, device-interface, implementation-contract, Phase 1 low-level and
predecessor-review documents are explicitly marked historical where ADR-009
supersedes their monolithic process, shared-database and polling assumptions.
Device protocol evidence and acceptance scenarios remain useful. The companion
architecture diagram now shows separate Asset-owned and Core-owned persistence.

### 2026-09-18: mtos_asset module checkpoint

The first service-boundary implementation establishes `mtos_asset` as the
canonical name for the existing electronic/virtual asset environment on port
5301. `src/mtos/asset_app.py` is its explicit application entry point and
`tools/mtos_asset` is the canonical start/stop/restart/status launcher.
`tools/asset_manager` remains a compatibility alias. Service lifecycle code
canonicalizes both spellings to the same `mtos_asset` lock, PID metadata and log,
preventing two aliases from launching duplicate processes. `/health` reports
`service: mtos_asset`.

The accepted roster domain, SQLite data, JSON APIs and iPhone-first UI were
preserved without redesign. This service imports no DCC or microcontroller
adapter and performs no device operation. The existing control configuration in
an asset remains descriptive inventory data.

ADR-008 image resource controls are now implemented: input is limited to 20 MiB
and 25 million decoded pixels, only one optimization runs at a time, and at most
four requests may wait. Excess concurrency receives a retryable busy error rather
than growing memory without bound. Directory imports use the same optimizer.

Focused Asset/domain/UI tests pass 65 with one optional environment test skipped.
The complete repository suite passes 71 with that same single skip. Python
compilation, launcher status smoke test and `git diff --check` also pass. The
roster UI was intentionally retained without visual changes because it had
already been accepted. No service was left running, and no commit or push was
performed.

### 2026-09-18: mtos_dcc and mtos_core module checkpoints

`mtos_dcc` is implemented as a loopback-only service on port 5304 with
`tools/mtos_dcc`. It exclusively owns serial discovery and the existing tested
DCC-EX station adapter. Its API is address-level and roster-independent. A fenced
Core session, six-second heartbeat watchdog, per-asset fencing tokens, 64-command
normal admission bound and emergency bypass enforce the ADR-009 boundary. Core
loss causes one best-effort DCC-EX all-stop when the station remains ready.

`mtos_core` is implemented on loopback port 5303 with `tools/mtos_core`. It owns
`data/db/core.sqlite3`, its command journal and reservation projection. It
validates locomotive eligibility through an Asset client contract, requests an
Asset lease, passes revision/lease/fence evidence to DCC, records uncertain
failures and deduplicates repeated command IDs before acquiring another lease or
touching hardware. Emergency stop is latched until explicit resume. A background
two-second heartbeat maintains the DCC session and affects Core readiness.

Both internal APIs require `X-MTOS-Internal-Token`; launchers bind them to
127.0.0.1 by default. Tests use fake Asset and DCC contracts. The real Asset lease
endpoint, HMI migration and end-to-end process wiring are deliberately deferred
to the integration checkpoint. No real CSB1 command was sent.

Focused DCC/Core/legacy-control/launcher tests pass 19. The complete repository
suite passes 77 with one optional browser-environment test skipped. Compilation
and `git diff --check` pass. Both services were smoke-started against a temporary
data root, returned correct health identities on 127.0.0.1:5304 and :5303, and
were stopped cleanly. No hardware was opened, and no commit or push was made.

### 2026-09-18: mtos_hmi module checkpoint

`mtos_hmi` is implemented as the LAN-facing service on port 5302 with
`tools/mtos_hmi`. `tools/asset_control` now canonicalizes to the same `mtos_hmi`
process, lock and PID metadata. HMI serves the accepted React/TypeScript control
interface but owns no roster database, serial object or MQTT client.

The browser adapter now uses `socket.io-client`; the one-second HTTP polling loop
was removed. Connection produces a full snapshot. Commands carry a generated
command ID, increasing client sequence, typed operation and payload. Socket
acknowledgement represents HMI acceptance only; background execution later emits
accepted/completed/failed events and a new snapshot. The server enforces eight
browser sessions, 32 outstanding commands per browser, 16 KiB commands, a 64 KiB
transport limit and a 1,024-event bounded history.

Flask-SocketIO and simple-websocket are runtime dependencies. The React production
bundle was rebuilt with socket.io-client. Focused HMI/service/legacy-control tests
pass 19; the full suite passes 81 with one optional browser-environment skip.
TypeScript compilation, Vite production build, Python compilation and whitespace
checks pass. A temporary loopback smoke service returned `mtos_hmi` health and
the React shell, then stopped cleanly.

The Core HMI projection endpoints remain the explicit integration contract, so
operational readiness requires the next integration checkpoint. No hardware was
opened, no DCC command was sent, and no commit or push was performed.

### 2026-09-18: Phase 1 service integration checkpoint

The DCC MAIN path is now integrated across `mtos_asset`, `mtos_dcc`, `mtos_core`
and `mtos_hmi`. Asset schema version 5 adds Asset-owned control leases and
per-asset fencing counters. Internal lease acquisition validates revisions and
conflicts atomically. A durable Core epoch lets a newly started Core session
supersede its own stale lease while issuing a higher asset fence; older or equal
epochs cannot take over it. Protected Asset edits are blocked by held or
unreconciled leases.

Core now exposes the HMI snapshot, active-locomotive roster, serial-device list
and typed command gateway. HMI monitors the loopback Core projection and pushes
only changed snapshots through Socket.IO, so the browser no longer polls. Device
connect/disconnect, identity, MAIN state, command outcomes and failures follow
the DCC-to-Core-to-HMI feedback path. While EX-CSB1 is disconnected, connection
is `disconnected` and MAIN power is truthfully `unknown`; startup never opens a
serial device, energizes track power or restores previous throttle state.

`tools/mtos_services` is the normal coordinator. It selects the project virtual
environment when present and otherwise the invoking system Python. Startup is
Asset, DCC, Core, fenced Core/DCC initialization, then HMI. A failure unwinds
the processes already started. Shutdown is HMI, Core, DCC, then Asset. Asset and
HMI bind to the trusted LAN on ports 5301 and 5302; Core and DCC stay on loopback
ports 5303 and 5304. The exact procedure and failure behavior are recorded in
`docs/operations/service-startup.md`.

The HMI is the intended common human console for locomotive and stationary-asset
operations, but this checkpoint implements DCC MAIN only. CV/PROG is Phase 2.
Turnout, signal and machine controls remain Phase 3 and require `mtos_mc`; no MC
operation is simulated or routed through DCC.

The full suite passes 83 tests with one optional environment test skipped.
Python compilation and whitespace validation pass. A real four-process smoke
test used an isolated temporary data root, verified health on ports 5301–5304,
observed the initial disconnected/power-unknown HMI Socket.IO snapshot, then
verified reverse-order shutdown and closed ports. No serial device was opened,
no hardware command was sent, and no commit or push was performed.

### 2026-09-18: mtos_mc design checkpoint

At this design checkpoint, before the later implementation checkpoint below,
the microcontroller boundary was finalized in
`docs/architecture/mtos-mc-module.md`. `mtos_mc` was specified to listen only on
`127.0.0.1:5305`, own MQTT/node sessions and a separate
`data/db/mc.sqlite3` execution ledger, and accept only fenced typed operations
from Core. Its public operational vocabulary is `turnout.set`, `signal.set` and
`machine.execute`. Raw MQTT topics, GPIO/channel numbers, PWM values and arbitrary
pulse timing never cross the Core/HMI boundary.

Turnout states remain `straight | diverging`; signals use the aspects allowed by
their type; machine actions must be declared by installed asset configuration.
The first machine is the water tank with action `operate`, gated on measurement
of its control interface and timing. Turntable positioning and chemical-plant
control remain deferred. Buffer-stop LEDs remain autonomous node-local flashing
indicators, not operator signal commands.

The specific water tank is Broadway Limited Imports 7924, Operating Water Tower
with Sound, UP, Weathered, HO. It uses a fused native 12 V accessory-bus tap before
the XL4015. MTOS omits the suggested DCC accessory decoder. The factory pushbutton
is preserved, with an isolated normally-open relay contact wired in parallel.
ESP32 firmware generates a bounded contact-closure pulse through a transistor/
MOSFET relay driver with required coil suppression; it never drives the factory
switch leads directly. Pulse duration, cycle busy window, trigger voltage/current,
polarity sensitivity, 12 V current, relay rating and final fuse require measurement.

One global servo permit covers all nodes and PCA9685 boards. An ordinary turnout
holds it for one SG90 sequence; a double slip holds it while both SG90s move
sequentially. Any future machine declaring a servo also consumes this permit.
Loss of evidence after dispatch produces `uncertain` and blocks all later servo
movement until node evidence or supervised reconciliation releases the permit.
Signals do not consume the servo permit, but share one serialized output-image
writer per node; Version 1 permits one global non-servo machine job.

MQTT Version 1 uses per-node command/event/availability/status topics, QoS 1,
non-retained commands, retained online/LWT and status, unique credentials and
topic ACLs. Node readiness requires fresh presence, boot ID, matching installed
revision, compatible firmware and a current producer-session handshake. QoS
PUBACK is never treated as physical completion. MC performs durable idempotency,
bounded evidence retention and restart reconciliation without blindly replaying
physical actions. Core state and results flow to the existing HMI Socket.IO
snapshot; HMI never connects to MQTT directly.

### 2026-09-18: service-owned database names

Persistent filenames now follow their owning services. The live Asset database
was atomically renamed from `data/db/mtos.sqlite3` to
`data/db/asset.sqlite3`, preserving 161 assets, 136 media records and all legacy
history; SQLite integrity is clean and the approved schema version 5 migration
was applied. `data/db/core.sqlite3` was initialized directly through the Core
repository without starting hardware services. MC adapter evidence now uses
`data/db/mc.sqlite3`.

DCC and HMI intentionally have no `dcc.sqlite3` or `hmi.sqlite3`: their Version 1
state is device/session state and a browser projection, respectively. Empty
databases are not created for naming symmetry. Backup/restore now uses
`asset.sqlite3`, includes `core.sqlite3` and `mc.sqlite3` when present,
and can still verify/restore older snapshots containing `mtos.sqlite3`.

The Asset file still contains 195 completed `control_command` rows and one stale
`control_reservation` from the superseded monolithic implementation. They were
preserved rather than deleted or silently transformed during the filename
migration. New canonical operational transactions belong to Core. Removal or
archival of those legacy tables requires a separate explicit migration.

### 2026-09-18: mtos_mc implementation checkpoint

The hardware-free MC implementation is complete. `mtos_mc` listens only on
`127.0.0.1:5305`, persists bounded subordinate execution evidence in
`data/db/mc.sqlite3`, accepts only fenced Core sessions, validates typed
`turnout.set`, `signal.set` and `machine.execute` requests, and publishes node
commands through a replaceable MQTT transport. Live MQTT is deliberately off by
default; `MTOS_MQTT_ENABLED=1` enables the Paho/Mosquitto adapter during
supervised commissioning.

The scheduler enforces one global servo permit across every node, sequential
actuation of both servos in a double slip, one serialized signal-output writer
per node and one Version 1 machine permit. A reboot observed after dispatch marks
the execution `uncertain`; an already dispatched servo retains the global gate.
Automatic stale-without-reboot transition remains pending, so matching evidence
or supervised reconciliation may be required. MQTT PUBACK is transport evidence only,
not physical completion. Node readiness requires presence, boot identity,
compatible firmware, matching configuration revision and the current Core/MC
producer-session handshake.

Core remains owner of the canonical operational transaction. MC execution
updates are reconciled back into Core and then reach browsers in the HMI
Socket.IO snapshot. HMI exposes Turnout, Signal and Machine tabs, obtains
stationary assets from Asset through Core, and disables physical controls until
the broker and selected node are ready. HMI never talks to MQTT directly.

Initial PlatformIO firmware under `firmware/esp32_node` covers ESP32 Wi-Fi/MQTT
sessions, retained availability/status, command deduplication, nonblocking SG90
sequences through one PCA9685, mutually exclusive signal images through one
74HC595, autonomous buffer-stop flashing and a bounded isolated-relay pulse for
the BLI 7924 water tower. Turnout position is persisted in ESP32 NVS and unknown
startup position fails closed. XL4015 and the 12 V/5 A supply are power hardware,
not software-addressed devices.

Host behavior is tested without electronics by a deterministic fake MQTT
transport. The full stack starts Asset, DCC, MC, Core and HMI in that order and
stops in reverse order. A temporary-data smoke test verified all five health
endpoints, fenced Core/DCC/MC initialization, truthful broker-offline HMI state
and clean shutdown. Physical pin assignments, electrical measurements,
Mosquitto ACLs, firmware flashing and end-to-end movement remain commissioning
work after the ordered hardware arrives. No code has been committed by Codex.

### 2026-09-18: repository documentation consistency checkpoint

All 32 project Markdown/README documents were reviewed after MC implementation.
Current documentation now consistently names Asset/HMI/Core/DCC/MC, ports
5301–5305, startup/shutdown order and service-owned `asset.sqlite3`,
`core.sqlite3` and `mc.sqlite3`. ADR-002 records the ADR-009 ownership amendment;
ADR-007 is host-independent while preserving its original SBC power planning;
ADR-008 points to the decomposed control services. The system-context diagram,
module checkpoints, operations guides and root README reflect the implemented
hardware-free MC path.

Monolithic `asset_control`, shared-database and polling documents are grouped and
labelled as historical baselines rather than silently rewritten. The MC design
now distinguishes implemented behavior from targets: terminal/event pruning,
automatic stale-dispatch uncertainty, full HMI reconciliation diagnostics,
systemd, live broker ACL/session validation, PlatformIO compilation and physical
commissioning remain pending. Firmware event publishing is presently QoS 0,
active-execution duplicates return busy rather than replaying state, and host
PUBACK evidence is not persisted; these are commissioning blockers against the
QoS 1 target contract. ADR-009 likewise identifies periodic lease renewal,
emergency-only bypass and sustained-load qualification as unimplemented targets.

Local Markdown links were checked with zero missing targets; all fenced code
blocks are balanced and `git diff --check` passes. The preceding software
checkpoint remains 96 tests passed with one optional browser smoke test skipped.
No commit or push was performed.

### 2026-09-18: live MC database initialized

`data/db/mc.sqlite3` was initialized directly through `McRepository` without
starting MC, MQTT or hardware. It is schema version 1; SQLite integrity is `ok`.
The empty live schema contains `metadata`, `execution`, `event`, `node` and
`asset_fence` plus the execution-state index. The file is operational data and
remains excluded from Git; `mtos_backup` includes it with Asset/Core databases.

### 2026-09-18: HMI initial-load timeout fix

The React acknowledgement helper emits an explicit null payload for read events.
The HMI snapshot, roster, device and stationary Socket.IO handlers previously
accepted zero arguments, so Flask-SocketIO raised `TypeError` and the browser
reported `HMI response timed out`. All four handlers now accept an optional
payload, and the regression test sends the same explicit null as the browser.
The full suite passes 96 tests with one optional browser test skipped. The running
HMI could not be restarted from the Codex process sandbox (`SIGTERM` permission
denied); the owner must run `tools/mtos_hmi restart` once to load the fix.

### 2026-09-20: Asset ownership and decoder-address programming checkpoint

Asset is authoritative for asset master data, including `lifecycle.status` and
`control.address`. An active Core lease or reservation does not veto a deliberate
Asset edit. When an Asset edit changes the operating view, Asset invalidates the
affected lease/projection so Core must reacquire and reconcile current data.
This preserves the owner's ability to place a locomotive into maintenance or
otherwise correct its inventory record without asking the operating subsystem.

Decoder-address changes now have two distinct workflows. The normal operational
workflow is `mtos_core` -> `mtos_dcc` -> EX-CSB1 PROG output -> verified decoder
readback -> revision-checked `mtos_asset` update. Core accepts only received,
maintenance-state, self-propelled DCC assets (`loco` or `mow`), durably records
the old/new address and Asset revision, and keeps uncertain physical outcomes for
reconciliation instead of retrying a write. DCC requires MAIN power to be
confirmed off and PROG to be confirmed available. Short addresses program CV1
and clear CV29 bit 5; long addresses program CV17/CV18 and set CV29 bit 5 while
preserving the remaining CV29 bits. Every affected CV is read back. Supported
addresses are 1 through 10239.

Asset still permits a direct inventory-only `control.address` correction because
it owns that field. The browser warns that this does not program or verify the
physical decoder. This escape hatch is intentional for imports, recovery and
manual correction; it can create a roster/decoder mismatch until reconciled.

The backend APIs and fake-serial tests are implemented. The Programming tab is
not yet enabled, and no claim is made that address programming has succeeded on
the real EX-CSB1 or a locomotive. General CV programming remains later work.
ADR-010 records the authoritative decision and supersedes older lease-blocking
and wholly-deferred address-programming descriptions. No live service, database,
serial device or locomotive was touched during this checkpoint.

### 2026-09-21: CV programming design checkpoint

CV programming and Cubietruck commissioning are now parallel workstreams. The
physical target is two permanently wired, fully isolated tracks: EX-CSB1 A to
`test_main_1` as MAIN and B to `test_prog_1` as PROG. Service-mode programming
requires one decoder on `test_prog_1`, a received DCC `loco` or self-propelled
`mow` asset in maintenance at that exact location, verified A/B roles and MAIN
power confirmed off.

The dedicated programming track may also support a bounded test run without
moving the locomotive. DCC-EX JOIN/DriveAway is the preferred commissioning
experiment because it temporarily sends the MAIN waveform to the PROG output;
explicitly switching B between PROG and MAIN is the fallback. Initial joined
tests require `test_main_1` clear, speed zero on entry, a low speed ceiling,
explicit stop/power-off/UNJOIN and verified restoration to B=PROG. Neither path
is treated as commissioned until exact EX-CSB1 feedback has been recorded.

The review found that the fake-tested address backend must be corrected before
hardware use. DCC-EX directs clients to use `<R>` for effective decoder address
and `<W address>` for address changes so consist and all required address CVs are
handled together. MTOS must replace its manual CV1/CV17/CV18/CV29 sequence, then
read the address again before Core conditionally updates Asset. Generic CV reads
and writes remain service-mode operations with write readback and no automatic
write retry. The HMI, API increments, state machine and staged commissioning are
specified in `docs/architecture/cv-programming-plan.md`. No hardware command was
sent and no implementation code was changed at this checkpoint.

The Programming UI must follow the familiar commercial-handset interaction with
two explicit actions: **Read Address** and **Write Address**. Read Address works
without a correct recorded address and does not modify Asset, supporting recovery
of locomotives that respond to neither address 3 nor their road number. It shows
the decoder result separately from the recorded Asset address. Write Address is
the guarded physical-programming and conditional-Asset-update workflow; a read
result is never silently persisted.

There is no routine third Save button. Write Address includes physical write,
decoder readback and the conditional Asset `control.address` update as one
coordinated operation. A verified-hardware/failed-Asset outcome becomes uncertain;
a later recovery increment must expose a contextual Reconcile action. Persistent per-section message areas
remain visible but carry no redundant “STATUS” caption.

### 2026-09-21: CV programming software checkpoint

The hardware-independent CV programming path is implemented across Asset, Core,
DCC and HMI. Asset exposes only received DCC locomotives/self-propelled MOW assets
in maintenance at `test_prog_1`. Core enforces that eligibility for writes,
journals each operation, and updates Asset `control.address` only after DCC
confirms a dedicated address write and an independent address readback. Read
Address can run without selecting an Asset so an unknown decoder can be
identified without changing inventory.

DCC now uses DCC-EX `<R>` and `<W address>` for effective decoder addressing;
the obsolete manual CV1/CV17/CV18/CV29 sequence has been removed. Generic CV
writes are followed by a correlated CV read and mismatch is a failure. The React
Programming tab contains track readiness, optional programming-Asset selection,
the one-decoder confirmation, distinct Recorded/Decoder/New address fields,
explicit Read Address and Write Address buttons, generic CV Read/Write controls,
and persistent per-section result areas without a redundant STATUS label. The
PROG-track test-mode panel remains disabled pending JOIN/DriveAway commissioning.

The production React bundle was rebuilt. Automated verification at this
checkpoint is 112 tests passed with one optional browser smoke test skipped;
TypeScript compilation and `git diff --check` pass. No serial, MQTT or other
hardware command was sent, and no commit or push was performed.

### 2026-09-21: shared UI language and protected Asset detail

The approved HMI/Asset comparison mock was applied to production. HMI function
keys now use the same proportional 2 px border, 10 px bevel, raised edge, padding
and touch geometry as the throttle step buttons while retaining the dark palette
and captionless persistent programming status lines.

Asset retains its existing light palette but adopts the shared panel, input,
button and picker geometry. Visible dropdowns are application-owned custom
pickers backed by native form selects, with compact symmetric option typography.
Existing asset details open read-only; **Edit Asset** unlocks fields and media
upload, **Cancel** reloads persisted data, and a successful Save restores View
mode. Add Asset remains editable. A persistent message line shows View, Edit or
Saved state without a STATUS caption.

The React production bundle was rebuilt; the Asset JavaScript passed syntax
validation, all 112 tests passed with one optional browser smoke test skipped,
and `git diff --check` passed. Development services remained stopped, no hardware
command was issued, and no commit or push was performed.
