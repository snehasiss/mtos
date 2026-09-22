"""Canonicalize decoder maker/model in the existing Asset control JSON."""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime

from mtos.assets.decoders import DECODER_MAKERS, canonical_decoder_maker, canonical_decoder_model
from mtos.roster import Roster


# Current-owner identifications and exact factory-model corrections.
OVERRIDES = {
    "L001": ("nce", "dual_mode"),
    "L005": ("esu", "loksound_5"),
    "L006": ("qsi", "quantum"),
    "L007": ("esu", "loksound_select"),
    "L010": ("esu", "loksound_5"),
    "L011": ("qsi", "quantum"),
    "L016": ("soundtraxx", "tsunami"),
    "L023": ("esu", "loksound_select"),
    "L039": ("esu", "loksound_select"),
    "L040": ("esu", "loksound_select"),
    "L041": ("esu", "loksound_select"),
    "L045": ("esu", "loksound_select"),
    "L056": ("esu", "loksound_5"),
    "L063": ("soundtraxx", "tsunami"),
    "L068": ("qsi", "quantum"),
    "L069": ("esu", "loksound_5"),
    "L070": ("esu", "loksound_select"),
    "L072": ("qsi", "quantum"),
    "L078": ("qsi", "quantum"),
    "L083": ("esu", "loksound_5"),
    "L085": ("digitrax", "sdh164k1b"),
    "L091": ("soundtraxx", "tsunami"),
    "L114": ("esu", "loksound_5"),
    "L116": ("esu", "loksound_5"),
    "L117": ("esu", "loksound_select"),
    "L125": ("qsi", "quantum"),
    "L128": ("qsi", "quantum"),
    "L140": ("mrc", "dual_mode"),
    "L143": ("esu", "loksound_5"),
    "L148": ("dcc_unknown", "dcc_sound_unknown"),
    "L151": ("trix", "mfx_plus_dcc"),
    "L152": ("digitrax", "dh126"),
    "L153": ("digitrax", "dh126"),
    "L154": ("digitrax", "dh126"),
    "M002": ("digitrax", "dh126"),
    "M003": ("bachmann", "21pin"),
}

LEGACY = {
    "dcc": ("unknown", None),
    "loksound": ("esu", "loksound_unspecified"),
    "esu loksound": ("esu", "loksound_unspecified"),
    "loksound5": ("esu", "loksound_5"),
    "esu loksound v5": ("esu", "loksound_5"),
    "paragon2": ("broadway_limited", "paragon2"),
    "paragon3": ("broadway_limited", "paragon3"),
    "paragon4": ("broadway_limited", "paragon4"),
    "tsunami": ("soundtraxx", "tsunami"),
    "tsunami2": ("soundtraxx", "tsunami2"),
    "econami": ("soundtraxx", "econami"),
    "soundtraxx value": ("soundtraxx", "sound_value"),
    "qsi": ("qsi", "quantum"),
    "digitrax": ("digitrax", None),
    "gm dcc92 4-function only": ("gaugemaster", "dcc92"),
    "bachmann 21 pin mtc": ("bachmann", "21pin"),
    "smartdecoder5.1": ("piko", "smartdecoder_5_1"),
}


def main():
    roster = Roster()
    with roster.lock():
        with roster.connect() as db:
            changes = []
            seen = set()
            for row in db.execute("SELECT asset_id,config FROM control ORDER BY asset_id"):
                control = json.loads(row["config"])
                decoder = control.get("decoder")
                if not decoder:
                    continue
                aid = row["asset_id"]
                seen.add(aid)
                if aid in OVERRIDES:
                    maker, model = OVERRIDES[aid]
                elif decoder.get("maker") in DECODER_MAKERS:
                    maker, model = decoder["maker"], decoder.get("model")
                else:
                    raw = decoder.get("model")
                    if raw is None:
                        raise ValueError(f"{aid} has no decoder model")
                    if str(raw).lower() not in LEGACY:
                        raise ValueError(f"Unmapped decoder: {aid}: {raw}")
                    maker, model = LEGACY[str(raw).lower()]
                canonical = {"maker": canonical_decoder_maker(maker), "model": canonical_decoder_model(model)}
                if decoder != canonical:
                    control["decoder"] = canonical
                    changes.append((aid, control))
            absent = set(OVERRIDES) - seen
            if absent:
                raise ValueError(f"Missing decoder records: {sorted(absent)}")
            if not changes:
                print("Decoder roster already canonical")
                return
            stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
            backup_path = roster.database.with_name(f"before-decoder-models-{stamp}.sqlite3")
            with sqlite3.connect(backup_path) as backup:
                db.backup(backup)
            print(f"Backup: {backup_path}")
        with roster.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            timestamp = datetime.now(UTC).isoformat()
            for aid, control in changes:
                db.execute("UPDATE control SET config=? WHERE asset_id=?", (json.dumps(control), aid))
                db.execute("UPDATE asset SET revision=revision+1,updated_at=? WHERE id=?", (timestamp, aid))
                db.execute("UPDATE lifecycle SET revision=revision+1,updated_at=? WHERE asset_id=?", (timestamp, aid))
                db.execute("DELETE FROM asset_lease WHERE asset_id=?", (aid,))
                db.execute("DELETE FROM control_reservation WHERE asset_id=?", (aid,))
            db.commit()
    print(f"Canonicalized {len(changes)} decoder records")


if __name__ == "__main__":
    main()
