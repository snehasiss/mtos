"""Upgrade the asset roster to the uniform control shape and family IDs."""

import json
import sqlite3


def upgrade(db, media_root):
    # SQLite cannot update referenced primary keys with foreign keys enabled.
    # The entire ID rewrite is checked before commit and rolled back on failure.
    db.execute("PRAGMA foreign_keys=OFF")
    try:
        db.execute("BEGIN IMMEDIATE")
        ids = {row[0] for row in db.execute("SELECT id FROM asset")}
        changes = {}
        for old, family in db.execute("SELECT id,family FROM asset WHERE id LIKE 'C___'"):
            prefix = {"passenger": "P", "freight": "F"}.get(family)
            if prefix is None:
                raise ValueError(f"Cannot migrate {old}: unexpected family {family}")
            new = prefix + old[1:]
            if new in ids or new in changes.values():
                raise ValueError(f"Cannot migrate {old}: {new} already exists")
            changes[old] = new

        for old, new in changes.items():
            for table, column in (
                ("asset", "id"), ("model", "asset_id"), ("prototype", "asset_id"),
                ("control", "asset_id"), ("control", "node_id"),
                ("component", "asset_id"), ("relation", "asset_id"),
                ("relation", "target_id"), ("lifecycle", "asset_id"),
                ("media", "asset_id"), ("consist_unit", "asset_id"),
                ("legacy_document", "asset_id"), ("control_command", "asset_id"),
                ("control_reservation", "asset_id"), ("asset_fence", "asset_id"),
                ("asset_lease", "asset_id"),
            ):
                db.execute(f"UPDATE {table} SET {column}=? WHERE {column}=?", (new, old))
            db.execute("UPDATE media SET filename=? || substr(filename, ?) "
                       "WHERE asset_id=? AND filename LIKE ?",
                       (new, len(old) + 1, new, old + "_%"))

        for aid, raw in db.execute("SELECT asset_id,config FROM control").fetchall():
            old = json.loads(raw)
            attrs = dict(old.get("attributes") or {})
            smoke = attrs.pop("smoke", False)
            sound = old.get("sound", attrs.pop("sound", False))
            attrs.pop("sound", None)
            attrs.pop("address", None)
            attrs.pop("decoder", None)
            dcc = old.get("dcc") is True
            decoder = dict(old.get("decoder") or {}) if dcc else {}
            if dcc:
                decoder.update(address=old.get("address", decoder.get("address")),
                               speed_steps=old.get("speed_steps", decoder.get("speed_steps")),
                               smoke=bool(smoke))
                decoder.setdefault("maker", None)
                decoder.setdefault("model", None)
            power = old.get("power")
            if power is None and attrs.get("type") in ("dc", "dcc"):
                power = "track_powered"
            control = {"dcc": dcc, "decoder": decoder, "sound": bool(sound),
                       "power": power, "node_id": old.get("node_id"), "attributes": attrs}
            db.execute("UPDATE control SET config=? WHERE asset_id=?", (json.dumps(control), aid))
        for (aid,) in db.execute("SELECT id FROM asset WHERE id NOT IN (SELECT asset_id FROM control)"):
            db.execute("INSERT INTO control(asset_id,node_id,config) VALUES(?,?,?)",
                       (aid, None, json.dumps({"dcc": False, "decoder": {}, "sound": False,
                                               "power": None, "node_id": None, "attributes": {}})))
        db.execute("UPDATE asset SET type='special_car' WHERE family='passenger' "
                   "AND type IN ('balcony','power_car')")
        db.execute("UPDATE asset SET type='industry' WHERE family='building' AND type='chemical_plant'")
        db.execute("PRAGMA user_version=6")
        failures = db.execute("PRAGMA foreign_key_check").fetchall()
        if failures:
            raise ValueError(f"Foreign key violations during control migration: {failures[:3]}")
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.execute("PRAGMA foreign_keys=ON")

    # Media files live under their family directory. Rename only after the
    # transaction succeeds; a rerun can finish an interrupted file rename.
    for old, new in changes.items():
        family = "passenger" if new.startswith("P") else "freight"
        folder = media_root / family
        for source in folder.glob(old + "_*"):
            destination = folder / (new + source.name[len(old):])
            if destination.exists():
                raise ValueError(f"Media migration target already exists: {destination}")
            source.rename(destination)
