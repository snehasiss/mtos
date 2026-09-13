"""Repeatable migration from union-pacific-layout; preserves every source JSON."""

import hashlib
import json
import re
from pathlib import Path

from .roster import Roster, now


def convert(document):
    identity = document["identity"]
    model = document.get("model", {})
    proto = document.get("prototype", {})
    family = identity["entity_type"]
    if family == "car":
        family = "passenger" if proto.get("purpose") == "passenger" else "freight"
    kind = (
        document.get("loco_type")
        or document.get("mow_type")
        or document.get("car_type")
    )
    kind = {
        "cleaner": "track_cleaner",
        "well_car": "intermodal",
        "generator_car": "power_car",
    }.get(kind, kind)
    old_status = model.get("status")
    warnings = []
    asset_id = identity["id"]
    if asset_id == "L046" and old_status == "active":
        life = {
            "possession": "received",
            "status": "active",
            "location": "test_main_1",
        }
    elif asset_id in ("M004", "L143"):
        life = {"possession": "shipped"}
    elif old_status in ("stored", "active"):
        life = {"possession": "received", "status": "stored"}
        if old_status == "active":
            warnings.append(
                f"{identity['id']}: active without block location; imported as stored"
            )
    elif old_status == "bought":
        life = {"possession": "ordered"}
        warnings.append(
            f"{identity['id']}: bought mapped to ordered; receipt not established"
        )
    elif old_status in (
        "intent",
        "spotted",
        "missed",
        "planned",
        "ordered",
        "shipped",
        "parked",
        "received",
    ):
        life = {
            "possession": {
                "intent": "planned",
                "spotted": "planned",
                "parked": "sheltered",
                "missed": "sheltered",
            }.get(old_status, old_status)
        }
        if old_status == "received":
            life["status"] = "stored"
    else:
        raise ValueError(f"Unmapped legacy status: {old_status}")
    life["acquisition"] = {k: model.get(k) for k in ("source", "price", "acquired")}
    if old_status in ("missed", "parked", "bought"):
        life["acquisition"]["legacy_possession"] = old_status
    # Legacy acquired does not establish receipt; retain the date without inventing received_on.
    p = {
        "maker": proto.get("builder"),
        "model": proto.get("model"),
        "reporting_mark": identity.get("reporting_mark"),
        "road_number": identity.get("road_number"),
        "attributes": {
            **{k: v for k, v in proto.items() if k not in ("builder", "model")},
            "railroad": identity.get("railroad"),
        },
    }
    if "self_propelled" in document:
        p["attributes"]["self_propelled"] = document["self_propelled"]
    old_control = document.get("control", {})
    control = {
        "attributes": {
            k: v
            for k, v in old_control.items()
            if k not in ("decoder", "address", "sound")
        },
        "dcc": old_control.get("type") == "dcc",
    }
    if control["dcc"]:
        control.update(
            address=old_control.get("address") or None,
            sound=bool(old_control.get("sound")),
            decoder={"model": old_control.get("decoder")},
        )
    else:
        control["attributes"].update(
            {k: old_control.get(k) for k in ("address", "sound", "decoder")}
        )
    return {
        "id": identity["id"],
        "family": family,
        "type": kind,
        "prototype": p,
        "model": {
            "maker": model.get("maker"),
            "scale": (model.get("scale") or "").lower(),
            "catalog_name": model.get("product"),
        },
        "control": control,
        "lifecycle": life,
        "notes": model.get("note"),
    }, warnings


def migrate(roster: Roster, source: Path, photos: Path):
    report = {
        "imported": 0,
        "skipped": 0,
        "media_imported": 0,
        "media_skipped": 0,
        "warnings": [],
        "errors": [],
    }
    if not source.is_dir() or not photos.is_dir():
        raise ValueError("Source data and photos must be existing directories")
    for path in sorted(source.rglob("*.json")):
        raw = path.read_text()
        document = json.loads(raw)
        key = str(path.relative_to(source))
        digest = hashlib.sha256(raw.encode()).hexdigest()
        with roster.connect() as db:
            old = db.execute(
                "SELECT sha256 FROM legacy_document WHERE source=?", (key,)
            ).fetchone()
        if old:
            if old[0] != digest:
                report["warnings"].append(
                    f"{key}: source changed since import; not overwritten"
                )
            report["skipped"] += 1
            continue
        aid = None
        if isinstance(document, dict) and "identity" in document:
            payload, warnings = convert(document)
            report["warnings"].extend(warnings)
            aid = payload["id"]
            try:
                roster.get(aid)
            except KeyError:
                roster.save(payload)
                report["imported"] += 1
            else:
                report["warnings"].append(
                    f"{aid}: already exists; preserved existing asset"
                )
        with roster.transaction() as db:
            db.execute(
                "INSERT INTO legacy_document VALUES(?,?,?,?,?)",
                (key, digest, aid, raw, now()),
            )
    for path in sorted(photos.iterdir()):
        if not path.is_file() or path.suffix.lower() != ".jpg":
            continue
        match = re.fullmatch(r"([A-Z][0-9]{3})-.+-([1-9][0-9]*)\.jpg", path.name)
        if not match:
            report["errors"].append(f"Unrecognized photo filename: {path.name}")
            continue
        try:
            copied = roster.put_media(match[1], int(match[2]), path)
            report["media_imported" if copied else "media_skipped"] += 1
        except (ValueError, KeyError, OSError) as error:
            report["errors"].append(f"{path.name}: {error}")
    return report
