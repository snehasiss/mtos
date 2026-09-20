"""SQLite roster persistence, transactional validation and media registration."""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import shutil
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from .assets.model import (
    ROLLING_FAMILIES,
    Asset,
    AssetFamily,
    AssetId,
    Component,
    Connection,
    Control,
    Decoder,
    Lifecycle,
    Model,
    Possession,
    PREFIXES,
    Prototype,
    Relation,
    Status,
    is_layout_location,
)


def now():
    return datetime.now(UTC).isoformat()


def data_root():
    return (
        Path(
            os.environ.get(
                "MTOS_DATA_DIR", Path(__file__).resolve().parents[2] / "data"
            )
        )
        .expanduser()
        .resolve()
    )


def operating_view(value):
    """The part of an asset that operating consumers (Core, DCC, MC) rely on."""
    return {
        "family": value.get("family"),
        "type": value.get("type"),
        "control": value.get("control"),
        "relations": value.get("relations", []),
        "lifecycle": {
            key: (value.get("lifecycle") or {}).get(key)
            for key in ("possession", "status", "location")
        },
    }


class Conflict(ValueError):
    pass


def merge(old, patch):
    result = dict(old)
    for key, value in patch.items():
        result[key] = (
            merge(result.get(key) or {}, value) if isinstance(value, dict) else value
        )
    return result


def validate(payload):
    """Parse the public JSON boundary through the domain values."""
    allowed = {
        "id",
        "family",
        "type",
        "label",
        "notes",
        "model",
        "prototype",
        "control",
        "components",
        "relations",
        "lifecycle",
        "revision",
        "created_at",
        "updated_at",
        "media",
    }
    if set(payload) - allowed:
        raise ValueError(f"Unknown fields: {sorted(set(payload) - allowed)}")
    for key in ("id", "family", "type"):
        if not isinstance(payload.get(key), str):
            raise ValueError(f"{key} must be a string")
    for key in ("model", "prototype", "control", "lifecycle"):
        if payload.get(key) is not None and not isinstance(payload[key], dict):
            raise ValueError(f"{key} must be an object")
    for key in ("components", "relations"):
        if payload.get(key) is not None and (
            not isinstance(payload[key], list)
            or not all(isinstance(item, dict) for item in payload[key])
        ):
            raise ValueError(f"{key} must be an array of objects")
    identity = AssetId(payload["id"])
    control = dict(payload.get("control") or {})
    if control.get("node_id"):
        control["node_id"] = AssetId(control["node_id"])
    if control.get("decoder"):
        control["decoder"] = Decoder(**control["decoder"])
    for key in ("address", "speed_steps"):
        if control.get(key) is not None and type(control[key]) is not int:
            raise ValueError(f"{key} must be an integer")
    for key in ("dcc", "sound"):
        if control.get(key) is not None and type(control[key]) is not bool:
            raise ValueError(f"{key} must be a boolean")
    components = []
    for raw in payload.get("components") or []:
        item = dict(raw)
        if item.get("connection"):
            if (
                not isinstance(item["connection"], dict)
                or type(item["connection"].get("channel")) is not int
            ):
                raise ValueError("Component connection requires an integer channel")
            item["connection"] = Connection(**item["connection"])
        components.append(Component(**item))
    asset = Asset(
        identity,
        AssetFamily(payload["family"]),
        payload["type"],
        label=payload.get("label"),
        notes=payload.get("notes"),
        model=Model(**payload["model"]) if payload.get("model") else None,
        prototype=Prototype(**payload["prototype"])
        if payload.get("prototype")
        else None,
        control=Control(**control) if control else None,
        components=tuple(components),
        relations=tuple(
            Relation(r["rel"], AssetId(r["asset_id"]), r["reason"])
            for r in payload.get("relations") or []
        ),
    )
    life = dict(payload.get("lifecycle") or {"possession": "planned"})
    acquisition = life.pop("acquisition", {})
    if not isinstance(acquisition, dict):
        raise ValueError("acquisition must be an object")
    if life.pop("asset_id", identity.value) != identity.value:
        raise ValueError("lifecycle asset_id does not match asset")
    life["possession"] = Possession(life.get("possession", "planned"))
    life["status"] = Status(life.get("status", "unavailable"))
    life["location"] = life.get("location") or "off_track"
    for key in ("purchased_on",):
        if life.get(key):
            life[key] = date.fromisoformat(life[key])
    if life.get("updated_at"):
        life["updated_at"] = datetime.fromisoformat(life["updated_at"])
    lifecycle = Lifecycle(identity, **life)
    if lifecycle.status in (Status.ACTIVE, Status.PARKED) and not is_layout_location(
        lifecycle.location
    ):
        raise ValueError("active or parked asset requires a layout location")
    normalized = asset.to_dict()
    normalized["lifecycle"] = lifecycle.to_dict()
    normalized["lifecycle"]["acquisition"] = acquisition
    return normalized


class Roster:
    def __init__(self, root=None):
        self.root = Path(root or data_root()).resolve()
        self.database = self.root / "db" / "asset.sqlite3"
        self.media = self.root / "media"
        self.database.parent.mkdir(parents=True, exist_ok=True)
        self.media.mkdir(parents=True, exist_ok=True)
        with self.lock():
            self._migrate_database_name()
            with self.connect() as db:
                self._migrate_schema(db)

    def _migrate_database_name(self):
        legacy = self.database.with_name("mtos.sqlite3")
        if self.database.exists() and legacy.exists():
            raise ValueError(
                "Both asset.sqlite3 and legacy mtos.sqlite3 exist; resolve the "
                "ambiguous Asset database before starting MTOS"
            )
        if not legacy.exists():
            return
        with sqlite3.connect(legacy) as db:
            db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        legacy.replace(self.database)
        for suffix in ("-wal", "-shm"):
            companion = Path(str(legacy) + suffix)
            if companion.exists():
                companion.replace(Path(str(self.database) + suffix))

    def _migrate_schema(self, db):
        version = db.execute("PRAGMA user_version").fetchone()[0]
        if version == 0:
            sql = (Path(__file__).parent / "migrations/001_roster.sql").read_text()
            db.executescript("BEGIN IMMEDIATE;\n" + sql + "\nCOMMIT;")
            version = 1
        if version == 1:
            sql = (
                Path(__file__).parent / "migrations/002_lifecycle.sql"
            ).read_text()
            db.executescript("BEGIN IMMEDIATE;\n" + sql + "\nCOMMIT;")
            version = 2
        if version == 2:
            safety = self.database.parent / "before-lifecycle-v3.sqlite3"
            if not safety.exists():
                with sqlite3.connect(safety) as backup:
                    db.backup(backup)
            sql = (
                Path(__file__).parent / "migrations/003-simple-lifecycle.sql"
            ).read_text()
            db.executescript("BEGIN IMMEDIATE;\n" + sql + "\nCOMMIT;")
            version = 3
        if version == 3:
            sql = (Path(__file__).parent / "migrations/004_control.sql").read_text()
            db.executescript("BEGIN IMMEDIATE;\n" + sql + "\nCOMMIT;")
            version = 4
        if version == 4:
            sql = (Path(__file__).parent / "migrations/005_asset_leases.sql").read_text()
            db.executescript("BEGIN IMMEDIATE;\n" + sql + "\nCOMMIT;")
            version = 5
        if version != 5:
            raise ValueError(f"Unsupported database schema: {version}")
        db.execute("PRAGMA journal_mode=WAL")
        self._migrate_media_layout(db)

    def acquire_leases(self, asset_ids, expected_revisions, core_session_id, core_epoch, purpose, duration_seconds=30):
        if not asset_ids or not all(isinstance(value, str) for value in asset_ids):
            raise ValueError("asset_ids must be a non-empty string list")
        if asset_ids != sorted(set(asset_ids)):
            raise ValueError("asset_ids must be unique and sorted")
        if not core_session_id or type(core_epoch) is not int or core_epoch < 1 or not purpose:
            raise ValueError("core_session_id, positive core_epoch and purpose required")
        if type(duration_seconds) is not int or not 5 <= duration_seconds <= 60:
            raise ValueError("duration_seconds must be 5..60")
        stamp = datetime.now(UTC)
        expires = (stamp + timedelta(seconds=duration_seconds)).isoformat()
        leases = []
        with self.transaction() as db:
            for asset_id in asset_ids:
                row = db.execute("SELECT revision FROM asset WHERE id=?", (asset_id,)).fetchone()
                if row is None:
                    raise KeyError(asset_id)
                expected = expected_revisions.get(asset_id)
                if type(expected) is not int or row["revision"] != expected:
                    raise Conflict(f"Asset revision changed: {asset_id}")
                current = db.execute("SELECT * FROM asset_lease WHERE asset_id=?", (asset_id,)).fetchone()
                supersede = current and current["core_session_id"] != core_session_id
                if supersede and core_epoch <= current["core_epoch"]:
                    raise Conflict(f"Asset is leased by another Core session: {asset_id}")
                if current and not supersede:
                    db.execute(
                        "UPDATE asset_lease SET purpose=?,state='held',expires_at=?,updated_at=? WHERE asset_id=?",
                        (purpose, expires, stamp.isoformat(), asset_id),
                    )
                    lease_id, token = current["lease_id"], current["fencing_token"]
                else:
                    fence = db.execute("SELECT token FROM asset_fence WHERE asset_id=?", (asset_id,)).fetchone()
                    token = (fence["token"] if fence else 0) + 1
                    db.execute(
                        "INSERT INTO asset_fence(asset_id,token) VALUES(?,?) "
                        "ON CONFLICT(asset_id) DO UPDATE SET token=excluded.token",
                        (asset_id, token),
                    )
                    lease_id = str(uuid.uuid4())
                    db.execute(
                        "INSERT INTO asset_lease VALUES(?,?,?,?,?,?,?,?,?,?,?) "
                        "ON CONFLICT(asset_id) DO UPDATE SET lease_id=excluded.lease_id,"
                        "fencing_token=excluded.fencing_token,asset_revision=excluded.asset_revision,"
                        "core_session_id=excluded.core_session_id,core_epoch=excluded.core_epoch,"
                        "purpose=excluded.purpose,state='held',expires_at=excluded.expires_at,"
                        "created_at=excluded.created_at,updated_at=excluded.updated_at",
                        (asset_id, lease_id, token, expected, core_session_id, core_epoch,
                         purpose, "held", expires, stamp.isoformat(), stamp.isoformat()),
                    )
                leases.append({"asset_id": asset_id, "lease_id": lease_id,
                               "fencing_token": token, "asset_revision": expected,
                               "expires_at": expires})
        return leases

    def _migrate_media_layout(self, db):
        """Move legacy media/<asset_id>/ files into media/<family>/ safely."""
        for row in db.execute(
            "SELECT m.asset_id,a.family,m.filename,m.sha256 FROM media m "
            "JOIN asset a ON a.id=m.asset_id"
        ):
            legacy = self.media / row["asset_id"] / row["filename"]
            canonical = self.media / row["family"] / row["filename"]
            if not legacy.exists():
                continue
            if canonical.exists():
                if hashlib.sha256(canonical.read_bytes()).hexdigest() != row["sha256"]:
                    raise Conflict(f"Conflicting media migration target: {canonical}")
                if hashlib.sha256(legacy.read_bytes()).hexdigest() != row["sha256"]:
                    raise Conflict(f"Damaged legacy media file: {legacy}")
                legacy.unlink()
            else:
                canonical.parent.mkdir(parents=True, exist_ok=True)
                legacy.rename(canonical)
            try:
                legacy.parent.rmdir()
            except OSError:
                pass

    def media_path(self, asset_id, filename, db=None):
        if db is None:
            with self.connect() as connection:
                return self.media_path(asset_id, filename, connection)
        row = db.execute("SELECT family FROM asset WHERE id=?", (asset_id,)).fetchone()
        if row is None:
            raise KeyError(asset_id)
        return self.media / row["family"] / filename

    @contextmanager
    def lock(self):
        self.root.mkdir(parents=True, exist_ok=True)
        with (self.root / ".lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            yield

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.database, timeout=30)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        try:
            yield db
        finally:
            db.close()

    @contextmanager
    def transaction(self):
        with self.lock(), self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                yield db
                db.commit()
            except Exception:
                db.rollback()
                raise

    def _get(self, db, asset_id):
        row = db.execute("SELECT * FROM asset WHERE id=?", (asset_id,)).fetchone()
        if row is None:
            raise KeyError(asset_id)
        result = dict(row)
        for table in ("model", "prototype", "lifecycle"):
            row = db.execute(
                f"SELECT * FROM {table} WHERE asset_id=?", (asset_id,)
            ).fetchone()
            if row:
                item = dict(row)
                item.pop("asset_id")
                for key in ("attributes", "acquisition"):
                    if key in item:
                        item[key] = json.loads(item[key])
                result[table] = item
        row = db.execute(
            "SELECT config FROM control WHERE asset_id=?", (asset_id,)
        ).fetchone()
        if row:
            result["control"] = json.loads(row[0])
        result["components"] = [
            json.loads(r[0])
            for r in db.execute(
                "SELECT config FROM component WHERE asset_id=? ORDER BY position",
                (asset_id,),
            )
        ]
        result["relations"] = [
            dict(r)
            for r in db.execute(
                "SELECT rel,target_id AS asset_id,reason FROM relation WHERE asset_id=?",
                (asset_id,),
            )
        ]
        result["media"] = {
            "base_url": f"/api/assets/{asset_id}/media/",
            "images": [
                dict(r)
                for r in db.execute(
                    "SELECT sequence,filename,width,height FROM media "
                    "WHERE asset_id=? ORDER BY sequence",
                    (asset_id,),
                )
            ],
        }
        return result

    def get(self, asset_id):
        with self.connect() as db:
            return self._get(db, asset_id)

    def operation_state(self, asset_id):
        """Whether operating consumers currently hold this asset (informational)."""
        with self.connect() as db:
            if db.execute("SELECT 1 FROM asset WHERE id=?", (asset_id,)).fetchone() is None:
                raise KeyError(asset_id)
            leased = db.execute(
                "SELECT 1 FROM asset_lease WHERE asset_id=? AND state='held' AND expires_at>?",
                (asset_id, datetime.now(UTC).isoformat()),
            ).fetchone()
            reserved = db.execute(
                "SELECT 1 FROM control_reservation WHERE asset_id=?", (asset_id,)
            ).fetchone()
        return {"leased": bool(leased), "reserved": bool(reserved)}

    def search(self, q="", family="", status="", limit=50, offset=0):
        limit = max(1, min(int(limit), 100))
        offset = max(0, int(offset))
        term = (
            "%" + q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        )
        where = " WHERE (?='' OR a.family=?) AND (?='' OR l.status=?) AND " + (
            "(a.id LIKE ? ESCAPE '\\' OR a.label LIKE ? ESCAPE '\\' OR "
            "p.reporting_mark LIKE ? ESCAPE '\\' OR p.road_number LIKE ? ESCAPE '\\' OR "
            "(p.reporting_mark || p.road_number) LIKE ? ESCAPE '\\' OR p.model LIKE ? ESCAPE '\\')"
        )
        params = (family, family, status, status, *([term] * 6))
        base = " FROM asset a LEFT JOIN prototype p ON p.asset_id=a.id LEFT JOIN lifecycle l ON l.asset_id=a.id"
        with self.connect() as db:
            total = db.execute("SELECT count(*)" + base + where, params).fetchone()[0]
            ids = db.execute(
                "SELECT a.id" + base + where + " ORDER BY a.id LIMIT ? OFFSET ?",
                (*params, limit, offset),
            )
            return {
                "items": [self._get(db, r[0]) for r in ids],
                "total": total,
                "limit": limit,
                "offset": offset,
            }

    def save(self, payload, *, asset_id=None, verified_address_change=False):
        if not isinstance(payload, dict):
            raise ValueError("JSON body must be an object")
        with self.transaction() as db:
            if asset_id:
                old = self._get(db, asset_id)
                if (
                    type(payload.get("revision")) is not int
                    or payload["revision"] != old["revision"]
                ):
                    raise Conflict("Asset changed. Reload before saving.")
                if payload.get("id", asset_id) != asset_id:
                    raise ValueError("Asset ID is immutable")
                merged = merge(old, payload)
                if merged.get("family") != old["family"] and old["media"]["images"]:
                    raise ValueError(
                        "Asset family cannot change while media is attached"
                    )
                revision = old["revision"] + 1
            else:
                merged = payload
                revision = 1
                if "id" not in merged:
                    raise ValueError("id is required")
                if db.execute(
                    "SELECT 1 FROM asset WHERE id=?", (merged["id"],)
                ).fetchone():
                    raise Conflict("Asset ID already exists")
            item = validate(merged)
            aid = item["id"]
            old_address = (old.get("control") or {}).get("address") if asset_id else None
            new_address = (item.get("control") or {}).get("address")
            if verified_address_change and (
                not asset_id or old_address == new_address
            ):
                raise ValueError("verified address update requires a changed address")
            # Asset is the authority. Operational records held by consumers never
            # block an edit; if what a consumer relies on changed, retire them and
            # let followers re-acquire against the new revision.
            operating_changed = bool(asset_id) and operating_view(old) != operating_view(item)
            timestamp = now()
            if asset_id:
                db.execute(
                    "UPDATE asset SET family=?,type=?,label=?,notes=?,revision=?,updated_at=? WHERE id=?",
                    (
                        item["family"],
                        item["type"],
                        item.get("label"),
                        item.get("notes"),
                        revision,
                        timestamp,
                        aid,
                    ),
                )
            else:
                db.execute(
                    "INSERT INTO asset VALUES(?,?,?,?,?,?,?,?)",
                    (
                        aid,
                        item["family"],
                        item["type"],
                        item.get("label"),
                        item.get("notes"),
                        revision,
                        timestamp,
                        timestamp,
                    ),
                )
            for table in (
                "model",
                "prototype",
                "control",
                "component",
                "relation",
                "lifecycle",
            ):
                db.execute(f"DELETE FROM {table} WHERE asset_id=?", (aid,))
            for table, columns in (
                (
                    "model",
                    ("scale", "maker", "product_number", "catalog_name", "released_on"),
                ),
                (
                    "prototype",
                    ("maker", "model", "reporting_mark", "road_number", "attributes"),
                ),
            ):
                if item.get(table):
                    values = [
                        json.dumps(item[table].get(c, {}))
                        if c == "attributes"
                        else item[table].get(c)
                        for c in columns
                    ]
                    db.execute(
                        f"INSERT INTO {table}(asset_id,{','.join(columns)}) VALUES({','.join('?' for _ in range(len(columns) + 1))})",
                        (aid, *values),
                    )
            if item.get("control"):
                ctrl = item["control"]
                node = ctrl.get("node_id")
                if (
                    node
                    and not db.execute(
                        "SELECT 1 FROM asset WHERE id=? AND family='node'", (node,)
                    ).fetchone()
                ):
                    raise ValueError("control.node_id must reference an existing node")
                db.execute(
                    "INSERT INTO control VALUES(?,?,?)", (aid, node, json.dumps(ctrl))
                )
            for i, c in enumerate(item.get("components", [])):
                db.execute(
                    "INSERT INTO component VALUES(?,?,?,?)",
                    (aid, c["ref"], i, json.dumps(c)),
                )
            for r in item.get("relations", []):
                db.execute(
                    "INSERT INTO relation VALUES(?,?,?,?)",
                    (aid, r["asset_id"], r["rel"], r["reason"]),
                )
            life = item["lifecycle"]
            db.execute(
                "INSERT INTO lifecycle VALUES(?,?,?,?,?,?,?,?)",
                (
                    aid,
                    life["possession"],
                    life.get("status"),
                    life.get("location"),
                    life.get("purchased_on"),
                    revision,
                    timestamp,
                    json.dumps(life.get("acquisition", {})),
                ),
            )
            if operating_changed:
                # asset_fence is kept, so the next lease gets a higher fencing token.
                db.execute("DELETE FROM asset_lease WHERE asset_id=?", (aid,))
                # A reservation also records the DCC address the locomotive is really
                # being driven on, which STOP must keep targeting. Retire it unless
                # this edit changed that address.
                if old_address == new_address or verified_address_change:
                    db.execute("DELETE FROM control_reservation WHERE asset_id=?", (aid,))
            self._validate_links(db)
            return self._get(db, aid)

    def _validate_links(self, db):
        for row in db.execute(
            "SELECT r.asset_id,r.target_id,s.location,t.location AS target_location,t.status "
            "FROM relation r JOIN lifecycle s ON s.asset_id=r.asset_id "
            "LEFT JOIN lifecycle t ON t.asset_id=r.target_id WHERE s.status='active'"
        ):
            if row["status"] != "active" or row["location"] != row["target_location"]:
                raise ValueError(
                    f"{row['asset_id']} requires active, co-located {row['target_id']}"
                )
        missing = db.execute(
            "SELECT a.id FROM asset a JOIN lifecycle l ON l.asset_id=a.id WHERE "
            "a.type='booster' AND l.status='active' AND NOT EXISTS(SELECT 1 FROM relation r "
            "JOIN asset t ON t.id=r.target_id WHERE r.asset_id=a.id AND r.reason='cab' "
            "AND t.family='loco' AND t.type!='booster')"
        ).fetchone()
        if missing:
            raise ValueError(f"{missing[0]} requires a cab locomotive")
        # Existing consists must remain rolling stock after edits.
        bad = db.execute(
            "SELECT u.asset_id FROM consist_unit u JOIN asset a ON a.id=u.asset_id "
            "WHERE a.family NOT IN ('loco','mow','passenger','freight')"
        ).fetchone()
        if bad:
            raise ValueError("Consists may contain only rolling stock")

    def consists(self):
        with self.connect() as db:
            return [
                dict(
                    r,
                    units=[
                        u[0]
                        for u in db.execute(
                            "SELECT asset_id FROM consist_unit WHERE consist_id=? ORDER BY position",
                            (r["id"],),
                        )
                    ],
                )
                for r in db.execute("SELECT * FROM consist ORDER BY id")
            ]

    def save_consist(self, payload, consist_id=None):
        from .assets.model import Consist, ConsistId

        item = Consist(
            ConsistId(consist_id or payload["id"]),
            tuple(AssetId(x) for x in payload["units"]),
            payload.get("label"),
        )
        with self.transaction() as db:
            old = db.execute(
                "SELECT revision FROM consist WHERE id=?", (item.id.value,)
            ).fetchone()
            if (consist_id and (not old or old[0] != payload.get("revision"))) or (
                not consist_id and old
            ):
                raise Conflict("Consist already exists or revision is stale")
            for unit in item.units:
                asset = self._get(db, unit.value)
                if AssetFamily(asset["family"]) not in ROLLING_FAMILIES:
                    raise ValueError("Consist units must be rolling stock")
            rev = old[0] + 1 if old else 1
            db.execute(
                "INSERT INTO consist VALUES(?,?,?,?) ON CONFLICT(id) DO UPDATE SET label=excluded.label,revision=excluded.revision,updated_at=excluded.updated_at",
                (item.id.value, item.label, rev, now()),
            )
            db.execute("DELETE FROM consist_unit WHERE consist_id=?", (item.id.value,))
            db.executemany(
                "INSERT INTO consist_unit VALUES(?,?,?)",
                [(item.id.value, i, u.value) for i, u in enumerate(item.units)],
            )
        return next(c for c in self.consists() if c["id"] == item.id.value)

    def next_asset_id(self, family):
        family = AssetFamily(family)
        prefix = PREFIXES[family]
        with self.connect() as db:
            used = {
                int(row[0][1:])
                for row in db.execute(
                    "SELECT id FROM asset WHERE id GLOB ?",
                    (prefix + "[0-9][0-9][0-9]",),
                )
            }
        for number in range(1, 1000):
            if number not in used:
                return f"{prefix}{number:03d}"
        raise Conflict(f"No asset IDs remain for prefix {prefix}")

    def put_media(self, asset_id, sequence, source, *, optimize=False):
        from PIL import Image

        from .image_optimizer import optimize_image

        if type(sequence) is not int or sequence < 1:
            raise ValueError("Image sequence must be positive")
        with self.transaction() as db:
            asset = self._get(db, asset_id)
            filename = f"{asset_id}_{sequence}.jpg"
            dest = self.media / asset["family"] / filename
            existing = db.execute(
                "SELECT sha256 FROM media WHERE asset_id=? AND sequence=?",
                (asset_id, sequence),
            ).fetchone()
            if existing:
                if (
                    not dest.is_file()
                    or hashlib.sha256(dest.read_bytes()).hexdigest() != existing[0]
                ):
                    raise Conflict(
                        f"Media is missing or damaged: {filename}; restore from backup"
                    )
                return False
            if dest.exists():
                raise Conflict(
                    f"Unregistered media file exists: {filename}; reconcile before importing"
                )
            dest.parent.mkdir(parents=True, exist_ok=True)
            try:
                if optimize:
                    optimize_image(Path(source), dest)
                else:
                    shutil.copyfile(source, dest)
                with Image.open(dest) as image:
                    image.verify()
                with Image.open(dest) as image:
                    width, height = image.size
                db.execute(
                    "INSERT INTO media VALUES(?,?,?,?,?,?,?,?)",
                    (
                        asset_id,
                        sequence,
                        filename,
                        hashlib.sha256(dest.read_bytes()).hexdigest(),
                        width,
                        height,
                        dest.stat().st_size,
                        now(),
                    ),
                )
            except Exception:
                dest.unlink(missing_ok=True)
                raise
            return True
