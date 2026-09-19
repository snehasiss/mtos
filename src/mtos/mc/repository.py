"""MC-owned bounded execution evidence and recovery state."""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path


def now():
    return datetime.now(UTC).isoformat()


class McRepository:
    def __init__(self, data_root):
        self.path = Path(data_root) / "db/mc.sqlite3"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript("""
            CREATE TABLE IF NOT EXISTS metadata(key TEXT PRIMARY KEY,value INTEGER NOT NULL);
            CREATE TABLE IF NOT EXISTS execution(
              execution_id TEXT PRIMARY KEY, command_id TEXT NOT NULL UNIQUE,
              payload_hash TEXT NOT NULL, payload TEXT NOT NULL,
              asset_id TEXT NOT NULL, node_id TEXT NOT NULL, operation TEXT NOT NULL,
              state TEXT NOT NULL, result TEXT, created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS execution_state_created ON execution(state,created_at);
            CREATE TABLE IF NOT EXISTS event(
              id INTEGER PRIMARY KEY AUTOINCREMENT, execution_id TEXT,
              kind TEXT NOT NULL, payload TEXT NOT NULL, created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS node(
              node_id TEXT PRIMARY KEY, boot_id TEXT, firmware TEXT,
              configuration_revision INTEGER, producer_session_id TEXT,
              availability TEXT NOT NULL, last_seen REAL, detail TEXT
            );
            CREATE TABLE IF NOT EXISTS asset_fence(
              asset_id TEXT PRIMARY KEY, fencing_token INTEGER NOT NULL
            );
            PRAGMA user_version=1;
            """)

    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA journal_mode=WAL")
        return db

    def next_epoch(self):
        with self.connect() as db:
            row = db.execute("SELECT value FROM metadata WHERE key='epoch'").fetchone()
            value = (row[0] if row else 0) + 1
            db.execute("INSERT INTO metadata VALUES('epoch',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (value,))
            return value

    def insert(self, request):
        payload = request.payload()
        payload["resources"] = list(request.resources)
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        stamp = now()
        with self.connect() as db:
            existing = db.execute(
                "SELECT * FROM execution WHERE execution_id=? OR command_id=?",
                (request.execution_id, request.command_id),
            ).fetchone()
            if existing:
                if existing["payload_hash"] != request.payload_hash:
                    raise ValueError("command or execution ID reused with another payload")
                return dict(existing), True
            db.execute(
                "INSERT INTO execution VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (request.execution_id, request.command_id, request.payload_hash, encoded,
                 request.asset_id, request.node_id, request.operation, "queued", None,
                 stamp, stamp),
            )
        return self.get(request.execution_id), False

    def get(self, execution_id):
        with self.connect() as db:
            row = db.execute("SELECT * FROM execution WHERE execution_id=?", (execution_id,)).fetchone()
        if not row:
            raise KeyError(execution_id)
        value = dict(row)
        value["payload"] = json.loads(value["payload"])
        value["result"] = json.loads(value["result"]) if value["result"] else None
        return value

    def queued(self):
        with self.connect() as db:
            rows = db.execute("SELECT execution_id FROM execution WHERE state='queued' ORDER BY created_at").fetchall()
        return [self.get(row[0]) for row in rows]

    def nonterminal(self):
        with self.connect() as db:
            rows = db.execute("SELECT execution_id FROM execution WHERE state NOT IN ('completed','rejected','failed','expired','cancelled') ORDER BY created_at").fetchall()
        return [self.get(row[0]) for row in rows]

    def recent(self, limit=100):
        with self.connect() as db:
            rows = db.execute("SELECT execution_id FROM execution ORDER BY updated_at DESC LIMIT ?", (limit,)).fetchall()
        return [self.get(row[0]) for row in rows]

    def transition(self, execution_id, state, result=None):
        stamp = now()
        with self.connect() as db:
            row = db.execute("SELECT state FROM execution WHERE execution_id=?", (execution_id,)).fetchone()
            if not row:
                raise KeyError(execution_id)
            db.execute("UPDATE execution SET state=?,result=?,updated_at=? WHERE execution_id=?",
                       (state, json.dumps(result) if result is not None else None, stamp, execution_id))
            db.execute("INSERT INTO event(execution_id,kind,payload,created_at) VALUES(?,?,?,?)",
                       (execution_id, state, json.dumps(result or {}), stamp))
        return self.get(execution_id)

    def check_and_advance_fence(self, asset_id, token):
        with self.connect() as db:
            row = db.execute("SELECT fencing_token FROM asset_fence WHERE asset_id=?", (asset_id,)).fetchone()
            if row and token < row[0]:
                return False
            db.execute("INSERT INTO asset_fence VALUES(?,?) ON CONFLICT(asset_id) DO UPDATE SET fencing_token=max(fencing_token,excluded.fencing_token)", (asset_id, token))
        return True

    def save_node(self, node):
        with self.connect() as db:
            db.execute("INSERT INTO node VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(node_id) DO UPDATE SET boot_id=excluded.boot_id,firmware=excluded.firmware,configuration_revision=excluded.configuration_revision,producer_session_id=excluded.producer_session_id,availability=excluded.availability,last_seen=excluded.last_seen,detail=excluded.detail",
                       (node["node_id"], node.get("boot_id"), node.get("firmware"), node.get("configuration_revision"), node.get("producer_session_id"), node["availability"], node.get("last_seen"), json.dumps(node.get("detail") or {})))

    def nodes(self):
        with self.connect() as db:
            return [dict(row) for row in db.execute("SELECT * FROM node ORDER BY node_id")]
