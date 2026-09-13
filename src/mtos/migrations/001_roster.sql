CREATE TABLE asset (
 id TEXT PRIMARY KEY CHECK(id GLOB '[A-Z][0-9][0-9][0-9]'),
 family TEXT NOT NULL, type TEXT NOT NULL, label TEXT, notes TEXT,
 revision INTEGER NOT NULL DEFAULT 1 CHECK(revision > 0),
 created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE INDEX asset_category ON asset(family, type);
CREATE TABLE model (
 asset_id TEXT PRIMARY KEY REFERENCES asset(id), scale TEXT, maker TEXT,
 product_number TEXT, catalog_name TEXT, released_on TEXT
);
CREATE TABLE prototype (
 asset_id TEXT PRIMARY KEY REFERENCES asset(id), maker TEXT, model TEXT,
 reporting_mark TEXT, road_number TEXT, attributes TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(attributes))
);
CREATE INDEX prototype_identity ON prototype(reporting_mark COLLATE NOCASE, road_number COLLATE NOCASE);
CREATE TABLE control (
 asset_id TEXT PRIMARY KEY REFERENCES asset(id), node_id TEXT REFERENCES asset(id),
 config TEXT NOT NULL CHECK(json_valid(config))
);
CREATE TABLE component (
 asset_id TEXT NOT NULL REFERENCES asset(id), ref TEXT NOT NULL,
 position INTEGER NOT NULL, config TEXT NOT NULL CHECK(json_valid(config)),
 PRIMARY KEY(asset_id,ref), UNIQUE(asset_id,position)
);
CREATE TABLE relation (
 asset_id TEXT NOT NULL REFERENCES asset(id), target_id TEXT NOT NULL REFERENCES asset(id),
 rel TEXT NOT NULL CHECK(rel='requires'), reason TEXT NOT NULL,
 PRIMARY KEY(asset_id,target_id,rel), CHECK(asset_id != target_id)
);
CREATE TABLE lifecycle (
 asset_id TEXT PRIMARY KEY REFERENCES asset(id),
 possession TEXT NOT NULL CHECK(possession IN ('planned','ordered','shipped','parked','received','missed')),
 status TEXT CHECK(status IN ('stored','active','maintenance','retired')),
 location TEXT, ordered_on TEXT, shipped_on TEXT, received_on TEXT, retired_on TEXT,
 revision INTEGER NOT NULL DEFAULT 1, updated_at TEXT NOT NULL,
 acquisition TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(acquisition)),
 CHECK((possession='received' AND status IS NOT NULL) OR (possession!='received' AND status IS NULL)),
 CHECK(status IS NOT 'active' OR length(trim(location)) > 0),
 CHECK((status IS 'retired') = (retired_on IS NOT NULL))
);
CREATE TABLE media (
 asset_id TEXT NOT NULL REFERENCES asset(id), sequence INTEGER NOT NULL CHECK(sequence >= 1),
 filename TEXT NOT NULL, view TEXT, caption TEXT, sha256 TEXT NOT NULL,
 width INTEGER NOT NULL, height INTEGER NOT NULL, size_bytes INTEGER NOT NULL,
 created_at TEXT NOT NULL, PRIMARY KEY(asset_id,sequence), UNIQUE(asset_id,filename)
);
CREATE TABLE consist (
 id TEXT PRIMARY KEY CHECK(id GLOB 'K[0-9][0-9][0-9]'), label TEXT,
 revision INTEGER NOT NULL DEFAULT 1, updated_at TEXT NOT NULL
);
CREATE TABLE consist_unit (
 consist_id TEXT NOT NULL REFERENCES consist(id) ON DELETE CASCADE,
 position INTEGER NOT NULL, asset_id TEXT NOT NULL REFERENCES asset(id),
 PRIMARY KEY(consist_id,position), UNIQUE(consist_id,asset_id)
);
CREATE TABLE legacy_document (
 source TEXT PRIMARY KEY, sha256 TEXT NOT NULL, asset_id TEXT REFERENCES asset(id),
 document TEXT NOT NULL CHECK(json_valid(document)), imported_at TEXT NOT NULL
);
PRAGMA user_version=1;
