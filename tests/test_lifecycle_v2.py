import fcntl
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from mtos.assets.model import LOCATIONS, AssetId, Lifecycle, Possession, Status
from mtos.backup import backup, restore_current, select_snapshot
from mtos.roster import Roster


def test_lifecycle_vocabulary_and_locations():
    assert [p.value for p in Possession] == [
        "planned",
        "ordered",
        "shipped",
        "sheltered",
        "received",
    ]
    assert [s.value for s in Status] == [
        "unavailable",
        "stored",
        "active",
        "parked",
        "maintenance",
        "retired",
    ]
    assert len(LOCATIONS) == 21
    for location in set(LOCATIONS) - {"off_track"}:
        Lifecycle(AssetId("L001"), Possession.RECEIVED, Status.PARKED, location)
    with pytest.raises(ValueError, match="location"):
        Lifecycle(AssetId("L001"), Possession.RECEIVED, Status.PARKED, "off_track")
    with pytest.raises(ValueError, match="location"):
        Lifecycle(AssetId("L001"), Possession.RECEIVED, Status.ACTIVE, "block25")


def test_schema_upgrade_preserves_old_values(tmp_path):
    root = tmp_path / "data"
    (root / "db").mkdir(parents=True)
    database = root / "db/mtos.sqlite3"
    with sqlite3.connect(database) as db:
        schema = (
            Path(__file__).resolve().parents[1] / "src/mtos/migrations/001_roster.sql"
        )
        db.executescript(schema.read_text())
        db.execute(
            "INSERT INTO asset VALUES('L001','loco','diesel',NULL,NULL,1,'2026-01-01','2026-01-01')"
        )
        db.execute(
            "INSERT INTO lifecycle(asset_id,possession,revision,updated_at) VALUES('L001','parked',1,'2026-01-01')"
        )
        db.execute(
            "UPDATE lifecycle SET ordered_on='2020-01-01',retired_on=NULL,"
            "acquisition='{\"acquired\":\"2020-02-03\"}' WHERE asset_id='L001'"
        )
    roster = Roster(root)
    life = roster.get("L001")["lifecycle"]
    assert life["possession"] == "sheltered"
    assert life["status"] == "unavailable"
    assert life["location"] == "off_track"
    assert life["purchased_on"] == "2020-02-03"
    assert life["acquisition"]["legacy_ordered_on"] == "2020-01-01"
    assert (root / "db/before-lifecycle-v3.sqlite3").is_file()
    assert life["acquisition"]["legacy_possession"] == "parked"
    with roster.connect() as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 5
        assert db.execute("PRAGMA foreign_key_check").fetchall() == []
    assert Roster(root).get("L001")["revision"] == 3


def test_manual_restore_preserves_previous_data_and_refuses_running_service(tmp_path):
    roster = Roster(tmp_path / "data")
    roster.save({"id": "L001", "family": "loco", "type": "diesel"})
    remote = tmp_path / "remote"
    remote.mkdir()
    snapshot = backup(roster, remote)
    assert select_snapshot(remote) == snapshot
    roster.save({"revision": 1, "label": "After backup"}, asset_id="L001")
    lifetime = tmp_path / ".data.services.lock"
    with lifetime.open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_SH)
        with pytest.raises(ValueError, match="Stop"):
            restore_current(snapshot, roster.root)
    restored, previous = restore_current(snapshot, roster.root)
    assert Roster(restored).get("L001")["label"] is None
    assert Roster(previous).get("L001")["label"] == "After backup"


def test_backup_requires_explicit_mode_and_asset_control_status_is_available(tmp_path):
    project = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [sys.executable, str(project / "tools/mtos_backup"), "--remote", str(tmp_path)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 2
    result = subprocess.run(
        [
            sys.executable,
            str(project / "tools/service.py"),
            "--service",
            "asset_control",
            "status",
        ],
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "MTOS_DATA_DIR": str(tmp_path / "data")},
    )
    assert result.returncode == 0 and "Stopped" in result.stdout
