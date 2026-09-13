# ADR-008: Normalized asset-management and roster domain

- **Status:** Accepted
- **Date:** 2026-09-13
- **Supersedes:** ADR-003

## Context

MTOS has two primary functions: asset management and layout operation. Autonomous
operation is aspirational. Version 1 first implements the asset-management roster;
speed, direction, turnout position, signal aspect, MQTT commands, and other live
operation state are explicitly outside this decision.

The model must remain small enough for an iPhone-first interface and an embedded
installation, without losing relational integrity. Python and Flask form the
application stack, SQLite is the authoritative store, and JSON is the API,
import/export, and fixture representation. Independent JSON files are not the live
store.

## Decision

### Normalized records

The domain has three independent records joined by IDs:

1. `asset` contains identity, descriptive master data, installed configuration,
   components, relations, and media metadata.
2. `lifecycle` contains changing possession and inventory state, keyed by
   `asset_id` with one current record per asset.
3. `consist` contains an ordered list of rolling-stock asset IDs.

An API may compose these records for a screen, but the stored records are not
duplicated. SQLite tables will normalize searchable fields and references; JSON
columns are reserved for genuinely variable attributes. Every database connection
enables foreign keys and coordinated changes use transactions.

### Asset identity and classification

Every asset has:

```json
{
  "id": "L001",
  "family": "loco",
  "type": "diesel"
}
```

`family` is used instead of `class`, because class also means a prototype railway
class and a software class. The former `desc` field is renamed `type`. Values use
snake case. `label` is optional; rolling stock is normally identified and searched
by `prototype.reporting_mark` and `prototype.road_number`.

| Family | Prefix | Version 1 types |
| --- | --- | --- |
| `loco` | `L` | `diesel`, `turbine`, `steam`, `booster` |
| `mow` | `M` | `tamper`, `mpv`, `track_cleaner`, `crane`, `snowplow` |
| `passenger` | `C` | `coach`, `balcony`, `heater_car`, `power_car`, `luggage`, `brakevan` |
| `freight` | `C` | `wagon`, `tanker`, `gondola`, `intermodal`, `flat_car`, `reefer` |
| `node` | `N` | `control_node` |
| `turnout` | `T` | `left`, `right`, `wye`, `crossing`, `double_slip` |
| `signal` | `G` | `ground_2a`, `mainline_3a`, `branchline_2a` |
| `machine` | `E` | `water_tank`, `turntable` |
| `building` | `B` | `engine_house`, `chemical_plant`, `station`, `warehouse`, `industry` |

Passenger `power_car` includes what may otherwise be called a generator car.
`intermodal` replaces the narrower `well_car`. There is no separate static versus
operating water-tank type; installed components and control configuration say
whether a particular `water_tank` is powered.

The prefixes are intentionally not globally mnemonic: passenger and freight both
use `C`. The full ID remains globally unique.

### Asset record

Only `id`, `family`, and `type` are mandatory. An asset can be entered quickly and
enriched later. A representative rolling-stock record is:

```json
{
  "id": "L001",
  "family": "loco",
  "type": "diesel",
  "model": {
    "scale": "ho",
    "maker": "broadway_limited",
    "product_number": "1234",
    "catalog_name": "emd_f7a"
  },
  "prototype": {
    "maker": "emd",
    "model": "f7a",
    "reporting_mark": "SAL",
    "road_number": "4202",
    "attributes": {
      "unit": "a",
      "cab": true
    }
  },
  "control": {
    "dcc": true,
    "address": 4202,
    "speed_steps": 128,
    "decoder": {
      "maker": "esu",
      "model": "lokpilot_5"
    },
    "sound": true
  }
}
```

The owned scale model is `model`; the represented 1:1 railway subject is
`prototype`. Searchable values use complete names such as `product_number`,
`road_number`, and `serial_number`.

`control` is configuration, not live control state. DCC equipment uses `dcc: true`.
DCC address kind is derived: 1 through 127 is short and 128 or greater is long.
Stationary assets omit `dcc` and reference a control node. There is no generic
node-local `control.address`; physical wiring belongs to components.

### Components and stationary assets

A component is an integral part without its own asset ID. A replaceable,
independently inventoried object is an asset and is linked by relation instead.
Component `ref` is unique within its parent asset.

A turnout stores its actuator and wiring once:

```json
{
  "id": "T012",
  "family": "turnout",
  "type": "left",
  "label": "West yard entrance",
  "control": { "node_id": "N001" },
  "components": [
    {
      "ref": "actuator",
      "type": "servo",
      "desc": "sg90",
      "connection": { "bus": "servo", "channel": 3 },
      "values": { "normal": 310, "reverse": 470 }
    }
  ]
}
```

There is no separate `outputs` array. `normal` and `reverse` are domain values;
their numbers are calibrated PCA9685 positions.

A three-aspect signal has three LED components:

```json
{
  "id": "G013",
  "family": "signal",
  "type": "mainline_3a",
  "control": { "node_id": "N002" },
  "components": [
    { "ref": "stop", "type": "led", "desc": "red",
      "connection": { "bus": "signal", "channel": 0 },
      "spec": { "resistor_ohm": 680 } },
    { "ref": "slow", "type": "led", "desc": "yellow",
      "connection": { "bus": "signal", "channel": 1 },
      "spec": { "resistor_ohm": 680 } },
    { "ref": "go", "type": "led", "desc": "green",
      "connection": { "bus": "signal", "channel": 2 },
      "spec": { "resistor_ohm": 680 } }
  ]
}
```

`ground_2a` and `branchline_2a` contain `stop` and `go`; `mainline_3a` contains
`stop`, `slow`, and `go`. These are mutually exclusive during operation. `dark` is
an electrical startup, shutdown, or fault condition, not a domain aspect. Current
aspect is operation state and is not stored in the asset record.

An SG90 belongs to a turnout. ESP32, PCA9685, 74HC595, and XL4015 devices belong
to a node. They are not independent assets.

### Lifecycle record

Lifecycle is separate from the asset master:

```json
{
  "asset_id": "L001",
  "possession": "received",
  "status": "active",
  "location": "test_main_1",
  "ordered_on": "2026-01-02",
  "shipped_on": "2026-01-08",
  "received_on": "2026-01-12",
  "revision": 4,
  "updated_at": "2026-09-13T10:00:00Z"
}
```

Possession values are:

```text
planned | ordered | shipped | sheltered | received
```

`sheltered` replaces the previous possession value `parked`. The `missed` value
has been removed. `parked` now belongs only to inventory status.

Status values are:

```text
stored | active | parked | maintenance | retired
```

`stored` includes boxed, `active` includes installed, and `maintenance` includes
repair and workshop work. `retired` is a status, not possession: a retired asset
can still be physically owned. A future disposition such as sold or scrapped can
be added separately if required.

`parked` means the asset is somewhere on the layout but is not actively operating.

Rules:

- Only `received` assets have an inventory status.
- A received asset must have a status.
- Active and parked assets must have a valid layout location.
- Every non-null location must belong to the following vocabulary:

```text
main_west_1, main_west_2, main_east_1, main_east_2
main_north_1, main_north_2, main_south_1, main_south_2
yard_west_1, yard_west_2, yard_west_3, yard_west_4
yard_south_1, yard_south_2, yard_south_3, yard_south_4
park_1, park_2, test_main_1, test_prog_1
```
- A retired asset has `retired_on`; records and IDs are retained and IDs are never
  reused.
- `scope` and display status are not part of version 1.
- `revision` supports optimistic concurrency for mobile edits.

### Relations

Relations are directional links between independent assets. Version 1 supports
`requires`; `reason` is a concise snake-case role supplied by the target, such as
`cab`, `booster`, `turbine`, or `aux_tank`.

```json
{
  "rel": "requires",
  "asset_id": "L001",
  "reason": "cab"
}
```

Thus a cabless `L002` booster may require cab-equipped `L001`, while `L001` can
remain active alone. When the source is active, required assets must be active and
co-located. Multipart equipment such as UP 28's cab, turbine, and auxiliary tank
uses the same mechanism when each part is independently inventoried.

### Consists

A consist is not an asset relation. It is a separately managed, ordered roster
aggregate:

```json
{
  "id": "K001",
  "label": "SAL F-unit consist",
  "units": ["L001", "L002"]
}
```

Order is lead to trailing. Unit IDs are stored directly for version 1; nested
objects are deferred until per-consist orientation or role is actually needed.
Every unit must exist, must be rolling stock, and cannot occur twice in one
consist. Creating or rearranging a consist does not modify asset master records.
Permanent physical dependencies remain in `relations` even when the assets also
appear in a consist.

### Media

Media metadata references an asset; binary data is not embedded in asset JSON or
SQLite. Files live below `data/media/<asset_id>/`. Stored filenames use the
asset ID and input sequence beginning at one:

```text
data/media/L001/L001_1.jpg
data/media/L001/L001_2.jpg
```

The composite `(asset_id, sequence)` identifies an image, so a separate global
media ID is unnecessary. Deleted sequence numbers are not reused and existing
files are not renumbered. For stationary assets without a reporting mark and road
number, the asset ID is the filename stem, for example
`data/media/G013/G013_1.jpg`.

The JSON media collection provides one generated `base_url` and filenames. The
base URL is not persisted because it depends on deployment:

```json
{
  "asset_id": "L001",
  "base_url": "/api/assets/L001/media/",
  "images": [
    { "filename": "L001_1.jpg", "view": "left_side" },
    { "filename": "L001_2.jpg", "view": "right_side" }
  ]
}
```

The utility in `tools/` scans a directory using:

```bash
python3 tools/import_image.py --source ~/Pictures/train-photos/
```

It resolves `REPORTINGMARKROADNUMBER_n.jpg` or `ASSETID_n.jpg` against the roster.
Other assets use direct IDs, e.g. `G013_1.jpg`; type-only filenames cannot identify
an individual asset. Unknown or ambiguous identities are reported without import.
All output uses `ASSETID_n.jpg`. Existing destinations are skipped.

Defaults are `data/db/mtos.sqlite3` and `data/media` relative to the project root;
`MTOS_DATA_DIR` or the utility's `--data-dir` overrides the root. The importer
queries `asset` and `prototype`, and registers each photo in the `media` table
through the same transaction/locking boundary used by Flask and backups.

Each new Pillow-supported source image has EXIF orientation applied, is converted
to RGB JPEG, and is fitted within a 1280-by-720 bounding box using high-quality
resampling. It is never stretched, cropped, or upscaled. JPEG output is progressive
and optimized. Input sequence numbers are preserved.

Media is operational user data and is excluded from the MTOS source repository.
Git history is not a backup mechanism for changing JPEG and SQLite data. The
SQLite database and the complete media tree form one backup unit. A consistent
backup first uses SQLite's online backup facility, then captures that database
copy and `data/media` in the same versioned snapshot. A plain one-way mirror is
insufficient because deletion or corruption would immediately propagate.

Backups are manually invoked using `tools/mtos_backup --remote ~/gdrive/backup/mtos/data --backup`.
The destination must already exist; removable media need not always be mounted.
No automation is installed. The same command may later be scheduled with cron by
the operator. SHA-256 manifests, database integrity checks and media checksums
are verified before a snapshot is published. `--restore` selects the newest
completed snapshot in the remote directory, verifies it, and replaces local data
only while services are stopped. Previous local data is retained in a dated
`data.before-restore-*` directory. `--restore-to` optionally targets a new
directory. Keep snapshots on a separate device.

## Application boundary

The service is `asset_manager`, on port 5301. Its launcher is
`tools/asset_manager (start|stop|restart|status)`. The future `asset_control`
service reserves port 5302 and `tools/asset_control`; no hardware control is
implemented as part of the asset-manager change.

The Python domain is served through a Flask JSON API and an iPhone-first HTML
interface. SQLite tables normalize asset, model, prototype, control, component,
relation, lifecycle, media, consist and ordered consist_unit records. Master and
lifecycle writes share one transaction and aggregate revision; stale edits fail
with HTTP 409. The legacy_document table preserves all migration source JSON,
including fields which have no direct equivalent. Acquisition source, price and
legacy acquisition date are retained in lifecycle.acquisition.

The UI supports add, search, edit, retirement through lifecycle status, ordered
consist editing, photo upload and gallery display. Configuration editing records
inventory information only; it does not program a decoder or actuate hardware.

Asset management does not publish MQTT commands or model live railroad operation.
Those concerns will receive separate decisions after the roster is complete.

## Consequences

- Master data, lifecycle state, and consists can change independently without
  duplicated JSON structures.
- SQLite provides atomicity, foreign keys, uniqueness, indexed roster searches,
  and safe concurrent mobile edits without a database server.
- JSON remains portable while external JSON edits cannot silently corrupt live
  state.
- Components contain physical wiring once; no parallel `outputs` structure exists.
- The same roster supports rolling and stationary assets without treating operation
  state as inventory.
