"""Core-owned operational journal and reservations."""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path


def now():
    return datetime.now(UTC).isoformat()


class CoreRepository:
    def __init__(self, data_root):
        root = Path(data_root)
        self.path = root / "db/core.sqlite3"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS command (
                    command_id TEXT PRIMARY KEY, asset_id TEXT, operation TEXT NOT NULL,
                    payload TEXT NOT NULL, state TEXT NOT NULL, outcome TEXT,
                    result TEXT,
                    created_at TEXT NOT NULL, updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS command_state_updated ON command(state, updated_at);
                CREATE TABLE IF NOT EXISTS reservation (
                    asset_id TEXT PRIMARY KEY, lease_id TEXT NOT NULL,
                    fencing_token INTEGER NOT NULL, asset_revision INTEGER NOT NULL,
                    address INTEGER, state TEXT NOT NULL, updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS core_metadata (
                    key TEXT PRIMARY KEY, value INTEGER NOT NULL
                );
                PRAGMA user_version=1;
                """
            )

    def next_epoch(self):
        with self.connect() as db:
            row = db.execute("SELECT value FROM core_metadata WHERE key='epoch'").fetchone()
            value = (row["value"] if row else 0) + 1
            db.execute(
                "INSERT INTO core_metadata(key,value) VALUES('epoch',?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (value,),
            )
            return value

    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA journal_mode=WAL")
        return db

    def begin(self, command_id, operation, payload, asset_id=None):
        stamp = now()
        with self.connect() as db:
            existing = db.execute("SELECT * FROM command WHERE command_id=?", (command_id,)).fetchone()
            encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
            if existing:
                if existing["operation"] != operation or existing["asset_id"] != asset_id or existing["payload"] != encoded:
                    raise RuntimeError("command_id was reused with another command")
                return dict(existing)
            db.execute(
                "INSERT INTO command VALUES(?,?,?,?,?,?,?,?,?)",
                (command_id, asset_id, operation, encoded, "accepted", None, None, stamp, stamp),
            )
        return None

    def existing(self, command_id, operation, payload, asset_id=None):
        if not command_id:
            return None
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        with self.connect() as db:
            row = db.execute("SELECT * FROM command WHERE command_id=?", (command_id,)).fetchone()
        if not row:
            return None
        if row["operation"] != operation or row["asset_id"] != asset_id or row["payload"] != encoded:
            raise RuntimeError("command_id was reused with another command")
        return dict(row)

    def finish(self, command_id, state, outcome=None, result=None):
        with self.connect() as db:
            db.execute(
                "UPDATE command SET state=?,outcome=?,result=?,updated_at=? WHERE command_id=?",
                (state, outcome, json.dumps(result) if result is not None else None, now(), command_id),
            )

    def reconcile_mc(self, executions):
        by_id = {item["execution_id"]: item for item in executions}
        with self.connect() as db:
            rows = db.execute("SELECT command_id,result FROM command WHERE state='accepted' AND result IS NOT NULL").fetchall()
            for row in rows:
                stored = json.loads(row["result"])
                execution = by_id.get(stored.get("execution_id"))
                if not execution:
                    continue
                state = execution["state"]
                if state not in {"completed", "failed", "rejected", "expired", "cancelled", "uncertain"}:
                    continue
                canonical = "completed" if state == "completed" else "uncertain" if state == "uncertain" else "failed"
                db.execute("UPDATE command SET state=?,outcome=?,result=?,updated_at=? WHERE command_id=?",
                           (canonical, state, json.dumps(execution), now(), row["command_id"]))

    def reserve(self, asset_id, lease, revision, address):
        with self.connect() as db:
            row = db.execute("SELECT * FROM reservation WHERE asset_id=?", (asset_id,)).fetchone()
            if row and (
                row["fencing_token"] > lease["fencing_token"]
                or (row["fencing_token"] == lease["fencing_token"] and row["lease_id"] != lease["lease_id"])
            ):
                raise RuntimeError("asset reservation requires reconciliation")
            db.execute(
                "INSERT INTO reservation VALUES(?,?,?,?,?,?,?) "
                "ON CONFLICT(asset_id) DO UPDATE SET lease_id=excluded.lease_id,"
                "fencing_token=excluded.fencing_token,asset_revision=excluded.asset_revision,"
                "address=excluded.address,state='held',updated_at=excluded.updated_at",
                (asset_id, lease["lease_id"], lease["fencing_token"], revision, address, "held", now()),
            )

    def reservation(self, asset_id):
        with self.connect() as db:
            row = db.execute("SELECT * FROM reservation WHERE asset_id=?", (asset_id,)).fetchone()
            return dict(row) if row else None

    def release(self, asset_id):
        with self.connect() as db:
            db.execute("DELETE FROM reservation WHERE asset_id=?", (asset_id,))
