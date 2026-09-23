# ADR-008: Normalized asset-management and roster domain

- **Status:** Accepted; proposed control amendment below awaits review
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

The add interface allocates the first available ID for the selected family's
prefix and displays it read-only before saving. Thus a machine proposes `E001`,
not the locomotive default `L001`. Passenger and freight search the same C-number
namespace. Allocation is advisory until the transactional insert; a concurrent
collision is rejected and the form must request the next ID again.

`family` is used instead of `class`, because class also means a prototype railway
class and a software class. The former `desc` field is renamed `type`. Values use
snake case. `label` is optional; rolling stock is normally identified and searched
by `prototype.reporting_mark` and `prototype.road_number`.

| Family | Prefix | Version 1 types |
| --- | --- | --- |
| `loco` | `L` | `diesel`, `turbine`, `steam`, `booster` |
| `mow` | `M` | `tamper`, `mpv`, `track_cleaner`, `crane`, `snowplow` |
| `passenger` | `C` | `coach`, `balcony`, `heater_car`, `power_car`, `luggage`, `brakevan` |
| `freight` | `C` | `wagon`, `tanker`, `gondola`, `intermodal`, `flat_car`, `reefer`, `caboose`, `tender` |
| `node` | `N` | `control_node` |
| `turnout` | `T` | `left`, `right`, `wye`, `crossing`, `double_slip` |
| `signal` | `G` | `ground_2a`, `mainline_3a`, `branchline_2a` |
| `machine` | `E` | `water_tank`, `turntable` |
| `building` | `B` | `engine_house`, `chemical_plant`, `station`, `warehouse`, `industry` |

Passenger `power_car` includes what may otherwise be called a generator car.
`intermodal` replaces the narrower `well_car`. There is no separate static versus
operating water-tank type; installed components and control configuration say
whether a particular `water_tank` is powered.

The freight `tender` type is for a separately inventoried auxiliary tender. A
tender permanently integral to one steam locomotive remains a component of that
locomotive rather than a separate asset.

The prefixes are intentionally not globally mnemonic: passenger and freight both
use `C`. The full ID remains globally unique.

### Asset record (current implementation)

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
Sound is an independent equipment capability: non-DCC rolling stock may have
`control: {"dcc": false, "sound": true}`. Decoder, DCC address, and speed steps
still require `dcc: true`; a DCC function decoder need not imply a traction motor.
DCC address kind is derived: 1 through 127 is short and 128 or greater is long.
Supported decoder addresses are 1 through 10239. Asset currently owns the persisted
`control.address`; ADR-010 distinguishes the coordinated Core/DCC programming
path from an explicitly warned inventory-only correction in the Asset UI.
Stationary assets currently omit `dcc` and reference a control node. There is no generic
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
      "values": { "straight": 310, "diverging": 470 }
    }
  ]
}
```

There is no separate `outputs` array. `straight` and `diverging` are domain values;
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

### Proposed amendment: one control shape for every asset (pending review)

The following is a **proposed replacement** for the compact `control` JSON above,
not the implemented schema. No code or data migration is authorized by this
draft. Every persisted asset and API response would carry the same outer keys:

```json
{
  "control": {
    "dcc": false,
    "decoder": {},
    "sound": false,
    "power": null,
    "node_id": null,
    "attributes": {}
  }
}
```

`dcc` says whether a DCC decoder receives commands; it does **not** say whether
the asset propels itself. `decoder` is `{}` when no decoder is installed. With
DCC, its fields are `maker`, `model`, `address`, `speed_steps`, and `smoke`.
Decoder address and speed-step mode move from `control` into `decoder`.
`speed_steps` may be `null` for a function-only decoder with no motor. Smoke is
recorded only inside `decoder`, reflecting the equipment covered by this plan;
there is no top-level `control.smoke`. `sound` remains outside `decoder` because
sound can exist without DCC. The three non-null `power` values are
`track_powered` (rail pickup), `self_powered` (onboard battery), and
`bus_powered` (layout accessory bus/control-node supply). `null` means the
source is not known. Neither track power nor sound implies DCC control.
`node_id` identifies the accessory control node, where applicable. `attributes`
remains the existing extension map; for example, `light: true` records lighting.

All IDs, addresses, channels, decoder identities, and function mappings below
are illustrative, not assignments to real equipment. Product classification
is separate from `control`: `loco.type` must describe the locomotive (such as
`diesel`, `turbine`, or `steam`), regardless of its decoder or sound equipment.
For passenger equipment, this amendment proposes one `special_car` type in
place of the current `balcony` and `power_car` types. Power, inspection,
business, and balcony cars all use `type: "special_car"`; their label,
prototype, model, and installed-control properties carry any useful detail.
There is no separate `power_car`, `inspection_car`, or `business_car` type in
the proposed classification. Existing passenger records using `balcony` or
`power_car` would be migrated to `special_car` only after this amendment is
approved.

**1. Non-sound DCC diesel locomotive**

```json
{
  "family": "loco", "type": "diesel",
  "control": {
    "dcc": true,
    "decoder": { "maker": "digitrax", "model": "dh126", "address": 3,
                 "speed_steps": 128, "smoke": false },
    "sound": false, "power": "track_powered", "node_id": null,
    "attributes": {}
  }
}
```

**2. Sound-equipped DCC turbine locomotive**

```json
{
  "family": "loco", "type": "turbine",
  "control": {
    "dcc": true,
    "decoder": { "maker": "esu", "model": "loksound_5", "address": 3,
                 "speed_steps": 128, "smoke": false },
    "sound": true, "power": "track_powered", "node_id": null,
    "attributes": {}
  }
}
```

**3. Sound- and smoke-equipped DCC 4-6-6-4 steam locomotive**

```json
{
  "family": "loco", "type": "steam",
  "prototype": { "model": "challenger",
                 "attributes": { "wheel_arrangement": "4-6-6-4" } },
  "control": {
    "dcc": true,
    "decoder": { "maker": "broadway_limited", "model": "paragon4", "address": 3800,
                 "speed_steps": 128, "smoke": true },
    "sound": true, "power": "track_powered", "node_id": null,
    "attributes": {}
  }
}
```

**4. BLI power car with sound, track pickup, and onboard switches**

```json
{
  "family": "passenger", "type": "special_car",
  "label": "UP Power Car 2066",
  "control": {
    "dcc": false, "decoder": {}, "sound": true,
    "power": "track_powered", "node_id": null, "attributes": {}
  }
}
```

This is **not** battery-powered and has no factory DCC decoder. Its local
switches need no extra control attributes for this inventory decision.

**5. BLI inspection car with lights, but no sound or DCC**

```json
{
  "family": "passenger", "type": "special_car",
  "label": "Track inspection car",
  "control": {
    "dcc": false, "decoder": {}, "sound": false,
    "power": "track_powered", "node_id": null,
    "attributes": { "light": true }
  }
}
```

**6. Non-self-propelled track cleaner controlled by a DCC function**

```json
{
  "family": "mow", "type": "track_cleaner",
  "control": {
    "dcc": true,
    "decoder": { "maker": null, "model": null, "address": null,
                 "speed_steps": null, "smoke": false },
    "sound": false, "power": "track_powered", "node_id": null,
    "attributes": {}
  }
}
```

The decoder and DCC address can be recorded when identified. No traction motor
or speed-step setting is implied. The exact cleaning function mapping is
outside this basic inventory shape.

**7. Peco SL-89 large-radius left-hand turnout**

```json
{
  "family": "turnout", "type": "left",
  "model": { "maker": "peco", "product_number": "SL-89" },
  "control": {
    "dcc": false, "decoder": {}, "sound": false,
    "power": "bus_powered", "node_id": "N001", "attributes": {}
  },
  "components": [
    { "ref": "actuator", "type": "servo", "desc": "turnout_servo",
      "connection": { "bus": "servo", "channel": 3 } }
  ]
}
```

The servo and wiring remain components, as in the accepted model.

**8. Two-aspect ground signal**

```json
{
  "family": "signal", "type": "ground_2a",
  "control": {
    "dcc": false, "decoder": {}, "sound": false,
    "power": "bus_powered", "node_id": "N002", "attributes": {}
  },
  "components": [
    { "ref": "stop", "type": "led", "desc": "red",
      "connection": { "bus": "signal", "channel": 0 } },
    { "ref": "go", "type": "led", "desc": "green",
      "connection": { "bus": "signal", "channel": 1 } }
  ]
}
```

**9. Stationary water tower: one node actuation triggers barrel movement and sound**

```json
{
  "family": "machine", "type": "water_tank",
  "control": {
    "dcc": false, "decoder": {}, "sound": true,
    "power": "bus_powered", "node_id": "N003", "attributes": {}
  },
  "components": [
    { "ref": "actuator", "type": "actuator", "desc": "barrel_and_sound",
      "connection": { "bus": "machine", "channel": 0 } }
  ]
}
```

One component connection represents the single actuation signal. `sound: true`
describes the tower's capability; it does not create a second command.

**10. BLI business car with track-powered, locally switched lights**

```json
{
  "family": "passenger", "type": "special_car",
  "label": "Business car",
  "control": {
    "dcc": false, "decoder": {}, "sound": false,
    "power": "track_powered", "node_id": null,
    "attributes": { "light": true }
  }
}
```

**11. Sound-equipped ScaleTrains reefer container, powered by a 9-volt battery**

```json
{
  "family": "container", "type": "reefer",
  "control": {
    "dcc": false, "decoder": {}, "sound": true,
    "power": "self_powered", "node_id": null, "attributes": {}
  }
}
```

`container` is an illustrative **new family**, not a currently accepted type;
its ID prefix and classification require a separate decision before entry.
The current `freight.reefer` type means a railcar, not a loose container.

**12. DC locomotive without a decoder (the L002 case)**

```json
{
  "family": "loco", "type": "diesel",
  "control": {
    "dcc": false, "decoder": {}, "sound": false,
    "power": "track_powered", "node_id": null,
    "attributes": { "light": true }
  }
}
```

This example does not change L002's database record. It shows why an empty
decoder object is more accurate than a `no_decoder` maker/model sentinel.

If a BLI car or sound-equipped container later receives a function decoder and
rail pickup, the same asset changes to `dcc: true`; its decoder identity and
address are then recorded inside `decoder`. Power changes to `track_powered`
only if its actual source changes. This proposal does not pre-record imagined
hardware, battery service, switch details, or DCC function mappings.

Implementation after approval requires one coordinated migration of stored
control JSON, serializer/API responses, form inputs, and Asset/Core/DCC address
consumers. ADR-010's address-ownership wording must then be updated to point to
`control.decoder.address`. Existing `control.attributes.smoke` values need
review before migration because the proposed typed value is `decoder.smoke`.
No application or database change is part of this draft.

Evidence for product examples: [Peco SL-89](https://peco-uk.com/products/turnout-large-radius-left-hand5),
[BLI Power Car 2066](https://broadway-limited.com/products/9124-union-pacific-power-car-2066-without-roof-antenna-with-sound-ho),
[BLI inspection-car touch lighting](https://broadway-limited.com/products/10177-conrail-type-track-inspection-car-unlettered-primer-gray-ho),
and [ScaleTrains sound reefer with 9-volt battery](https://www.scaletrains.com/operator-ho-scale-cimc-53-reefer-container-cr-england.html).
The BLI cars' track pickup and local-switch behavior are owner-verified details.

### Lifecycle record

Lifecycle is separate from the asset master:

```json
{
  "asset_id": "L001",
  "possession": "received",
  "status": "active",
  "location": "test_main_1",
  "purchased_on": "2026-01-02",
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
unavailable | stored | active | parked | maintenance | retired
```

`unavailable` is the explicit default before receipt. `stored` includes boxed,
`active` includes installed, and `maintenance` includes
repair and workshop work. `retired` is a status, not possession: a retired asset
can still be physically owned. A future disposition such as sold or scrapped can
be added separately if required.

`parked` means the asset is somewhere on the layout but is not actively operating.

Rules:

- Assets not yet received have status `unavailable`.
- Active and parked assets must have a valid layout location.
- Every non-null location must belong to the following vocabulary:

```text
off_track
main_west_1, main_west_2, main_east_1, main_east_2
main_north_1, main_north_2, main_south_1, main_south_2
yard_west_1, yard_west_2, yard_west_3, yard_west_4
yard_south_1, yard_south_2, yard_south_3, yard_south_4
park_1, park_2, test_main_1, test_prog_1
```
- `off_track` is the explicit default location; active and parked require another
  enumerated layout location.
- Lifecycle stores one optional `purchased_on` date. Other milestone dates are
  not part of v1; migration retains prior values in acquisition metadata. Records
  and IDs are retained on retirement and IDs are never reused.
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
SQLite. Files are grouped by asset family under `data/media/<family>/`. Stored
filenames use the globally unique asset ID and input sequence beginning at one:

```text
data/media/loco/L001_1.jpg
data/media/loco/L001_2.jpg
```

The composite `(asset_id, sequence)` identifies an image, so a separate global
media ID is unnecessary. Deleted sequence numbers are not reused and existing
files are not renumbered. For stationary assets without a reporting mark and road
number, the asset ID is the filename stem, for example
`data/media/signal/G013_1.jpg`. Family is resolved from the authoritative asset
record, never inferred from a filename. This keeps manual media inspection useful
without creating one directory per asset. Asset family cannot be changed while
media is attached; this prevents database and filesystem placement from diverging.

The JSON media collection provides one generated `base_url` and filenames. The
base URL is not persisted because it depends on deployment:

```json
{
  "asset_id": "L001",
  "base_url": "/api/assets/L001/media/",
  "images": [
    { "filename": "L001_1.jpg" },
    { "filename": "L001_2.jpg" }
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
All output uses `data/media/<family>/ASSETID_n.jpg`. Existing destinations are skipped.

Defaults are `data/db/asset.sqlite3` and `data/media` relative to the project root;
`MTOS_DATA_DIR` or the utility's `--data-dir` overrides the root. The importer
queries `asset` and `prototype`, and registers each photo in the `media` table
through the same transaction/locking boundary used by Flask and backups.

Each new Pillow-supported source image has EXIF orientation applied, is converted
to RGB JPEG, center-cropped to 16:9, and resized within a 1280-by-720 maximum using
high-quality resampling. It is never stretched or upscaled. This gives library
cards, detail galleries, directory imports, and HTTP uploads one predictable
aspect ratio. JPEG output is progressive and optimized. Input sequence numbers
are preserved.

Image processing is explicitly bounded because compressed file size does not
bound decoded memory. Version 1 accepts at most 20 MiB compressed input and
25,000,000 decoded pixels. Dimensions are inspected before conversion or resize;
decompression-bomb and over-limit images are rejected. `mtos_asset` performs one
optimization at a time with a bounded waiting queue of four requests; a full
queue returns a busy response rather than accumulating memory. Bulk directory
import is a maintenance operation and must not run during live railroad
operation. These are safety/resource limits, not changes to the 1280x720 JPEG
output contract.

Media is operational user data and is excluded from the MTOS source repository.
Git history is not a backup mechanism for changing JPEG and SQLite data. The
databases, media and every other file under `data/` form one continuity unit.

ADR-013 supersedes the earlier removable-directory snapshot procedure for the
deployed Cubietruck. The Admin service now synchronizes the complete stopped
`data/` tree to a separate host using rsync over key-authenticated SSH. It stages
and validates a restore and retains the previous local tree. The destination is
an exact current mirror; historical snapshots, if required, are created on the
remote host.

## Application boundary

The service is `mtos_asset`, on port 5301. Its launcher is
`tools/mtos_asset (start|stop|restart|status)`; `tools/asset_manager` is a
compatibility alias for the same process. ADR-009 later decomposed operation:
`mtos_hmi` uses port 5302, `mtos_core` uses 5303, `mtos_dcc` uses 5304 and
`mtos_mc` uses 5305. `tools/asset_control` is now a compatibility alias for
`mtos_hmi`. This ADR still governs inventory ownership and does not define live
operational state.

The Python domain is served through a Flask JSON API and an iPhone-first HTML
interface. SQLite tables normalize asset, model, prototype, control, component,
relation, lifecycle, media, consist and ordered consist_unit records. Master and
lifecycle writes share one transaction and aggregate revision; stale edits fail
with HTTP 409. The legacy_document table preserves all migration source JSON,
including fields which have no direct equivalent. Acquisition source, price and
legacy acquisition date are retained in lifecycle.acquisition.

The UI supports add, search, protected read-only detail viewing, explicit edit,
retirement through lifecycle status, ordered
consist editing, photo upload and gallery display. The mobile asset form does not
expose raw JSON for components, relations, or variable attributes; ordinary edits
preserve those values. A future technical interface or CLI may manage them.
Configuration editing records inventory information only; it does not program a
decoder or actuate hardware.

Existing details default to View mode to reduce accidental mobile edits. Edit is
an explicit state; Cancel discards the browser form by reloading persisted data,
and Save returns to View mode. Add Asset remains directly editable. The light
Asset palette is retained while control geometry and custom picker behavior are
shared with HMI.

Asset management does not publish MQTT commands or model live railroad operation.
ADR-009 and the MC low-level design assign those concerns to Core and MC.

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
