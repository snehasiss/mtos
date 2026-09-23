"""Shared-SQLite control records and eligible roster projection."""

from __future__ import annotations

import hashlib
import json
import uuid

from ..roster import Conflict, Roster, now


def config_hash(asset):
    protected = {
        "family": asset["family"],
        "type": asset["type"],
        "control": asset.get("control"),
        "relations": asset.get("relations", []),
        "lifecycle": {
            key: asset["lifecycle"].get(key)
            for key in ("possession", "status", "location")
        },
    }
    return hashlib.sha256(
        json.dumps(protected, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


class ControlRepository:
    def __init__(self, root=None):
        self.roster = Roster(root)

    def locomotives(self):
        result = self.roster.search(family="loco", limit=100)["items"]
        items = []
        for asset in result:
            reason = self.ineligible_reason(asset)
            if reason:
                continue
            proto = asset.get("prototype") or {}
            items.append(
                {
                    "id": asset["id"],
                    "reporting_mark": proto.get("reporting_mark"),
                    "road_number": proto.get("road_number"),
                    "prototype": proto.get("model"),
                    "address": ((asset.get("control") or {}).get("decoder") or {}).get("address"),
                }
            )
        return items

    def operating_asset(self, asset_id):
        asset = self.roster.get(asset_id)
        reason = self.ineligible_reason(asset)
        if reason:
            raise Conflict(reason)
        return asset

    def ineligible_reason(self, asset):
        if asset["family"] != "loco":
            return "Asset is not a locomotive"
        life = asset["lifecycle"]
        if life["possession"] != "received" or life["status"] != "active":
            return "Locomotive must be received and active"
        control = asset.get("control") or {}
        address = (control.get("decoder") or {}).get("address")
        if control.get("dcc") is not True or type(address) is not int or not 1 <= address <= 10239:
            return "Locomotive requires a valid DCC configuration"
        return None

    def reserve(self, asset, session_id):
        stamp = now()
        address = asset["control"]["decoder"]["address"]
        digest = config_hash(asset)
        with self.roster.transaction() as db:
            row = db.execute(
                "SELECT owner_session,config_hash FROM control_reservation WHERE asset_id=?",
                (asset["id"],),
            ).fetchone()
            if row and (row["owner_session"] != session_id or row["config_hash"] != digest):
                raise Conflict("Locomotive is reserved by another control session")
            db.execute(
                "INSERT INTO control_reservation VALUES(?,?,?,?,?,?,?) "
                "ON CONFLICT(asset_id) DO UPDATE SET owner_session=excluded.owner_session,address=excluded.address,config_hash=excluded.config_hash,state='held',updated_at=excluded.updated_at",
                (asset["id"], session_id, address, digest, "held", stamp, stamp),
            )
        return address

    def command(self, kind, asset_id, payload, state="finished", outcome=None):
        command_id, stamp = str(uuid.uuid4()), now()
        with self.roster.transaction() as db:
            db.execute(
                "INSERT INTO control_command VALUES(?,?,?,?,?,?,?,?)",
                (command_id, asset_id, kind, json.dumps(payload), state, outcome, stamp, stamp),
            )
        return command_id

    def release(self, asset_id, session_id):
        with self.roster.transaction() as db:
            row = db.execute(
                "SELECT owner_session,state FROM control_reservation WHERE asset_id=?", (asset_id,)
            ).fetchone()
            if not row:
                return
            if row["owner_session"] != session_id or row["state"] != "held":
                raise Conflict("Reservation requires reconciliation")
            db.execute("DELETE FROM control_reservation WHERE asset_id=?", (asset_id,))
