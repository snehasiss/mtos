CREATE TABLE asset_fence (
    asset_id TEXT PRIMARY KEY REFERENCES asset(id) ON DELETE CASCADE,
    token INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE asset_lease (
    asset_id TEXT PRIMARY KEY REFERENCES asset(id) ON DELETE CASCADE,
    lease_id TEXT NOT NULL UNIQUE,
    fencing_token INTEGER NOT NULL,
    asset_revision INTEGER NOT NULL,
    core_session_id TEXT NOT NULL,
    core_epoch INTEGER NOT NULL,
    purpose TEXT NOT NULL,
    state TEXT NOT NULL CHECK(state IN ('held','expired_pending_reconciliation')),
    expires_at TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX asset_lease_session ON asset_lease(core_session_id, state);
PRAGMA user_version=5;
