CREATE TABLE control_command (
 command_id TEXT PRIMARY KEY,
 asset_id TEXT REFERENCES asset(id),
 kind TEXT NOT NULL,
 payload TEXT NOT NULL CHECK(json_valid(payload)),
 state TEXT NOT NULL CHECK(state IN ('pending','sent','finished','uncertain')),
 outcome TEXT,
 created_at TEXT NOT NULL,
 updated_at TEXT NOT NULL
);
CREATE INDEX control_command_state_updated ON control_command(state,updated_at);

CREATE TABLE control_reservation (
 asset_id TEXT PRIMARY KEY REFERENCES asset(id),
 owner_session TEXT NOT NULL,
 address INTEGER,
 config_hash TEXT NOT NULL,
 state TEXT NOT NULL CHECK(state IN ('held','uncertain')),
 created_at TEXT NOT NULL,
 updated_at TEXT NOT NULL
);
PRAGMA user_version=4;
