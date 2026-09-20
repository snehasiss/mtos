import io
import json

import pytest
from PIL import Image

from mtos.app import create_app
from mtos.backup import backup, restore, verify
from mtos.legacy import migrate
from mtos.roster import Conflict, Roster


@pytest.fixture
def roster(tmp_path):
    return Roster(tmp_path / "data")


def loco(aid="L001", **kwargs):
    return dict(id=aid, family="loco", type="diesel", **kwargs)


def test_database_roundtrip_search_and_concurrent_edits(roster):
    roster.save(
        loco(
            prototype={
                "reporting_mark": "SAL",
                "road_number": "4202",
                "attributes": {"cab": True},
            },
            model={"scale": "ho", "maker": "Example"},
            lifecycle={"possession": "received", "status": "stored"},
        )
    )
    assert roster.database.parent.name == "db"
    assert roster.database.name == "asset.sqlite3"
    assert roster.search("sal4202")["total"] == 1
    assert roster.search("' OR 1=1 --")["total"] == 0
    updated = roster.save({"revision": 1, "label": "Cab unit"}, asset_id="L001")
    assert updated["prototype"]["attributes"]["cab"] is True
    assert updated["revision"] == 2
    with pytest.raises(Conflict):
        roster.save({"revision": 1, "label": "Stale edit"}, asset_id="L001")
    assert roster.get("L001")["label"] == "Cab unit"
    with roster.connect() as db:
        assert db.execute("PRAGMA foreign_keys").fetchone()[0] == 1


def test_legacy_database_filename_is_migrated_once(tmp_path):
    root = tmp_path / "data"
    original = Roster(root)
    original.save(loco())
    legacy = root / "db" / "mtos.sqlite3"
    original.database.replace(legacy)

    migrated = Roster(root)

    assert migrated.database.name == "asset.sqlite3"
    assert migrated.get("L001")["family"] == "loco"
    assert migrated.database.is_file()
    assert not legacy.exists()


def test_invalid_lifecycle_or_node_rolls_back_entire_asset(roster):
    roster.save(loco())
    with pytest.raises(ValueError):
        roster.save(
            {
                "revision": 1,
                "label": "Invalid",
                "lifecycle": {
                    "possession": "shipped",
                    "status": "active",
                    "location": "test_main_1",
                },
            },
            asset_id="L001",
        )
    assert roster.get("L001")["revision"] == 1
    with pytest.raises(ValueError):
        roster.save(
            {
                "id": "T001",
                "family": "turnout",
                "type": "left",
                "control": {"node_id": "N001"},
            }
        )
    with pytest.raises(KeyError):
        roster.get("T001")


def test_reverse_dependency_blocks_retirement(roster):
    active = {"possession": "received", "status": "active", "location": "test_main_1"}
    roster.save(loco(lifecycle=active))
    roster.save(
        {
            "id": "L002",
            "family": "loco",
            "type": "booster",
            "lifecycle": active,
            "relations": [{"rel": "requires", "asset_id": "L001", "reason": "cab"}],
        }
    )
    with pytest.raises(ValueError, match="requires"):
        roster.save(
            {
                "revision": 1,
                "lifecycle": {"status": "retired", "location": "off_track"},
            },
            asset_id="L001",
        )
    assert roster.get("L001")["lifecycle"]["status"] == "active"


def test_consist_order_and_stale_revision(roster):
    roster.save(loco())
    roster.save(loco("L002"))
    roster.save_consist({"id": "K001", "units": ["L002", "L001"]})
    assert roster.consists()[0]["units"] == ["L002", "L001"]
    roster.save_consist({"revision": 1, "units": ["L001", "L002"]}, "K001")
    with pytest.raises(Conflict):
        roster.save_consist({"revision": 1, "units": ["L001"]}, "K001")
    assert roster.consists()[0]["units"] == ["L001", "L002"]


def test_flask_library_create_update_upload_and_csrf(tmp_path):
    app = create_app({"DATA_ROOT": tmp_path / "data", "TESTING": True})
    client = app.test_client()
    page = client.get("/")
    assert page.status_code == 200
    assert client.get("/health").json["service"] == "mtos_asset"
    assert b"mtos-logo-wireframe.png" in page.data
    assert b'aria-label="Previous page">\xe2\x86\x90</button>' in page.data
    assert b'aria-label="Next page">\xe2\x86\x92</button>' in page.data
    assert client.get("/static/mtos-logo-wireframe.png").status_code == 200
    schema = client.get("/api/schema").json
    assert {"caboose", "tender"} <= set(schema["families"]["freight"])
    assert b'name="view"' not in page.data and b'name="caption"' not in page.data
    assert b'name="components"' not in page.data
    assert b'name="relations"' not in page.data
    assert b'name="attributes"' not in page.data
    assert b'name="purchased_on"' in page.data and b'name="retired_on"' not in page.data
    script = client.get("/static/roster.js").data
    assert b"card-top" in script
    assert b"builder-model" in script
    assert b"asset-id" in script
    assert b"asset.prototype?.maker,asset.prototype?.model" in script
    assert client.post("/api/assets", json=loco()).status_code == 403
    token = client.get("/api/session").json["csrf"]
    headers = {"X-CSRF-Token": token}
    assert client.get("/api/next-asset-id?family=machine").json == {"id": "E001"}
    assert client.get("/api/next-asset-id?family=loco").json == {"id": "L001"}
    assert client.post("/api/assets", json=loco(), headers=headers).status_code == 201
    assert client.get("/api/next-asset-id?family=loco").json == {"id": "L002"}
    assert (
        client.patch(
            "/api/assets/L001", json={"revision": 1, "label": "Test"}, headers=headers
        ).status_code
        == 200
    )
    assert (
        client.patch(
            "/api/assets/L001", json={"revision": 1, "label": "Stale"}, headers=headers
        ).status_code
        == 409
    )
    image = io.BytesIO()
    Image.new("RGB", (1600, 900)).save(image, format="JPEG")
    image.seek(0)
    response = client.post(
        "/api/assets/L001/media",
        headers=headers,
        data={"image": (image, "photo.jpg"), "sequence": "1"},
    )
    assert response.status_code == 201
    assert response.json["images"][0]["width"] == 1280
    assert response.json["images"][0]["height"] == 720
    assert "view" not in response.json["images"][0]
    assert "caption" not in response.json["images"][0]
    assert client.get("/api/assets/L001/media/L001_1.jpg").status_code == 200
    assert client.get("/api/assets/L001/media/anything.jpg").status_code == 404
    assert client.get("/api/assets?q=Test").json["total"] == 1


def test_asset_control_lease_is_atomic_renewable_and_asset_edits_release_it(tmp_path):
    app = create_app({"DATA_ROOT": tmp_path / "data", "TESTING": True, "INTERNAL_TOKEN": "secret"})
    roster = app.extensions["roster"]
    asset = roster.save(loco(
        prototype={"reporting_mark": "UP", "road_number": "28"},
        control={"dcc": True, "address": 28},
        lifecycle={"possession": "received", "status": "active", "location": "test_main_1"},
    ))
    client = app.test_client()
    internal = {"X-MTOS-Internal-Token": "secret"}
    request = {
        "asset_ids": ["L001"], "expected_revisions": {"L001": asset["revision"]},
        "core_session_id": "core-1", "core_epoch": 1,
        "purpose": "throttle", "duration_seconds": 30,
    }
    assert client.post("/internal/control-leases", json=request).status_code == 403
    first = client.post("/internal/control-leases", headers=internal, json=request)
    assert first.status_code == 200
    renewed = client.post("/internal/control-leases", headers=internal, json=request)
    assert renewed.json["leases"][0]["lease_id"] == first.json["leases"][0]["lease_id"]
    assert renewed.json["leases"][0]["fencing_token"] == 1
    with roster.connect() as db:
        db.execute(
            "UPDATE asset_lease SET expires_at='2000-01-01T00:00:00+00:00' WHERE asset_id='L001'"
        )
    after_idle = client.post("/internal/control-leases", headers=internal, json=request)
    assert after_idle.status_code == 200
    assert after_idle.json["leases"][0]["lease_id"] == first.json["leases"][0]["lease_id"]
    assert after_idle.json["leases"][0]["fencing_token"] == 1
    other = client.post(
        "/internal/control-leases", headers=internal,
        json={**request, "core_session_id": "core-2"},
    )
    assert other.status_code == 409
    superseded = client.post(
        "/internal/control-leases", headers=internal,
        json={**request, "core_session_id": "core-2", "core_epoch": 2},
    )
    assert superseded.status_code == 200
    assert superseded.json["leases"][0]["fencing_token"] == 2
    token = client.get("/api/session").json["csrf"]
    changed = client.patch(
        "/api/assets/L001", headers={"X-CSRF-Token": token},
        json={"revision": asset["revision"], "control": {"dcc": True, "address": 29}},
    )
    assert changed.status_code == 200  # Asset is the authority; a hold never vetoes an edit
    assert changed.json["revision"] == asset["revision"] + 1
    with roster.connect() as db:
        assert db.execute("SELECT count(*) FROM asset_lease").fetchone()[0] == 0
    descriptive = client.patch(
        "/api/assets/L001", headers={"X-CSRF-Token": token},
        json={"revision": changed.json["revision"], "label": "Still editable"},
    )
    assert descriptive.status_code == 200
    locomotives = client.get("/internal/operating-locomotives", headers=internal)
    assert locomotives.status_code == 200
    assert locomotives.json["items"][0]["id"] == "L001"
    assert locomotives.json["items"][0]["address"] == 29


def test_internal_programmed_address_update_is_authenticated_and_revision_checked(tmp_path):
    app = create_app({"DATA_ROOT": tmp_path / "data", "TESTING": True, "INTERNAL_TOKEN": "secret"})
    roster = app.extensions["roster"]
    roster.save(loco(
        control={"dcc": True, "address": 3},
        lifecycle={"possession": "received", "status": "maintenance"},
    ))
    client = app.test_client()
    path = "/internal/assets/L001/programmed-address"
    assert client.patch(path, json={"revision": 1, "address": 28}).status_code == 403
    updated = client.patch(
        path,
        headers={"X-MTOS-Internal-Token": "secret"},
        json={"revision": 1, "address": 28},
    )
    assert updated.status_code == 200
    assert updated.json["control"]["address"] == 28
    assert updated.json["revision"] == 2
    stale = client.patch(
        path,
        headers={"X-MTOS-Internal-Token": "secret"},
        json={"revision": 1, "address": 29},
    )
    assert stale.status_code == 409


def test_backup_restores_database_and_media_and_detects_corruption(roster, tmp_path):
    roster.save(loco())
    image = tmp_path / "photo.jpg"
    Image.new("RGB", (100, 100)).save(image)
    roster.put_media("L001", 1, image)
    remote = tmp_path / "external"
    remote.mkdir()
    snapshot = backup(roster, remote)
    verify(snapshot)
    restored = restore(snapshot, tmp_path / "restored")
    assert (
        Roster(restored).get("L001")["media"]["images"][0]["filename"] == "L001_1.jpg"
    )
    assert (restored / "media/loco/L001_1.jpg").read_bytes() == image.read_bytes()
    with pytest.raises(ValueError):
        restore(snapshot, restored)
    with (snapshot / "media/loco/L001_1.jpg").open("ab") as stream:
        stream.write(b"bad")
    with pytest.raises(ValueError, match="integrity"):
        verify(snapshot)
    with pytest.raises(ValueError, match="already exist"):
        backup(roster, tmp_path / "unmounted")


def test_legacy_asset_folder_backup_still_verifies_and_restores(roster, tmp_path):
    roster.save(loco())
    image = tmp_path / "photo.jpg"
    Image.new("RGB", (30, 20), "green").save(image)
    roster.put_media("L001", 1, image)
    remote = tmp_path / "external"
    remote.mkdir()
    snapshot = backup(roster, remote)
    canonical = snapshot / "media/loco/L001_1.jpg"
    legacy = snapshot / "media/L001/L001_1.jpg"
    legacy.parent.mkdir()
    canonical.rename(legacy)
    canonical.parent.rmdir()
    manifest_path = snapshot / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["files"]["media/L001/L001_1.jpg"] = manifest["files"].pop(
        "media/loco/L001_1.jpg"
    )
    manifest_path.write_text(json.dumps(manifest, indent=2))

    verify(snapshot)
    restored = restore(snapshot, tmp_path / "restored-old-layout")
    migrated = Roster(restored)
    assert (migrated.media / "loco/L001_1.jpg").read_bytes() == image.read_bytes()
    assert not (migrated.media / "L001").exists()


def test_legacy_import_preserves_source_and_is_repeatable(roster, tmp_path):
    source = tmp_path / "legacy"
    source.mkdir()
    photos = tmp_path / "photos"
    photos.mkdir()
    document = {
        "identity": {
            "id": "L001",
            "entity_type": "loco",
            "reporting_mark": "UP",
            "road_number": "28",
        },
        "loco_type": "turbine",
        "prototype": {"builder": "GE"},
        "model": {
            "status": "active",
            "price": 20,
            "source": "Shop",
            "acquired": "2021-06-01",
        },
        "control": {"type": "dc", "address": 0},
    }
    raw = json.dumps(document)
    (source / "L001.json").write_text(raw)
    Image.new("RGB", (100, 100)).save(photos / "L001-UP28-1.jpg")
    report = migrate(roster, source, photos)
    assert report["imported"] == 1 and report["media_imported"] == 1
    assert report["warnings"]
    assert roster.get("L001")["lifecycle"]["acquisition"]["price"] == 20
    assert roster.get("L001")["lifecycle"]["purchased_on"] == "2021-06-01"
    with roster.connect() as db:
        assert db.execute("SELECT document FROM legacy_document").fetchone()[0] == raw
    again = migrate(roster, source, photos)
    assert again["imported"] == 0 and again["media_skipped"] == 1
    assert (source / "L001.json").read_text() == raw


@pytest.mark.parametrize(
    ("asset_id", "old_status", "possession", "status", "location"),
    [
        ("L046", "active", "received", "active", "test_main_1"),
        ("M004", "bought", "shipped", "unavailable", "off_track"),
        ("L143", "missed", "shipped", "unavailable", "off_track"),
    ],
)
def test_confirmed_legacy_lifecycle_corrections(
    roster, tmp_path, asset_id, old_status, possession, status, location
):
    source = tmp_path / "legacy"
    source.mkdir()
    photos = tmp_path / "photos"
    photos.mkdir()
    document = {
        "identity": {
            "id": asset_id,
            "entity_type": "loco" if asset_id != "M004" else "mow",
        },
        "loco_type": "diesel" if asset_id != "M004" else None,
        "mow_type": "tamper" if asset_id == "M004" else None,
        "model": {"status": old_status},
    }
    (source / f"{asset_id}.json").write_text(json.dumps(document))
    report = migrate(roster, source, photos)
    assert report["errors"] == []
    lifecycle = roster.get(asset_id)["lifecycle"]
    assert (
        lifecycle["possession"],
        lifecycle.get("status"),
        lifecycle.get("location"),
    ) == (
        possession,
        status,
        location,
    )



def _operating_loco(roster):
    """An active DCC loco that Core holds (lease) and the control service reserved."""
    import sqlite3

    roster.save(
        loco(
            lifecycle={"possession": "received", "status": "active", "location": "main_west_1"},
            control={"dcc": True, "address": 46},
        )
    )
    lease = roster.acquire_leases(["L001"], {"L001": 1}, "core-1", 1, "throttle")[0]
    with sqlite3.connect(roster.database) as db:
        db.execute(
            "INSERT INTO control_reservation VALUES('L001','ctl-session-1',46,'hash','held',"
            "'2026-01-01T00:00:00+00:00','2026-01-01T00:00:00+00:00')"
        )
    return lease


def _holds(roster):
    import sqlite3

    with sqlite3.connect(roster.database) as db:
        return (
            db.execute("SELECT count(*) FROM asset_lease").fetchone()[0],
            db.execute("SELECT count(*) FROM control_reservation").fetchone()[0],
        )


@pytest.mark.parametrize("status", ["parked", "maintenance", "stored", "retired"])
def test_asset_status_change_is_never_blocked_by_operating_holds(roster, status):
    _operating_loco(roster)
    saved = roster.save({"revision": 1, "lifecycle": {"status": status}}, asset_id="L001")
    assert saved["lifecycle"]["status"] == status
    assert saved["revision"] == 2
    assert _holds(roster) == (0, 0)  # followers must re-acquire; nothing stays orphaned


def test_status_change_releases_orphaned_reservation_and_lease(roster):
    """A reservation left by a dead control session must not pin the asset."""
    _operating_loco(roster)
    import sqlite3

    with sqlite3.connect(roster.database) as db:
        db.execute("UPDATE asset_lease SET expires_at='2000-01-01T00:00:00+00:00'")
    roster.save({"revision": 1, "lifecycle": {"status": "parked"}}, asset_id="L001")
    assert _holds(roster) == (0, 0)


def test_release_keeps_fencing_monotonic_and_invalidates_old_revision(roster):
    old = _operating_loco(roster)
    roster.save({"revision": 1, "lifecycle": {"status": "parked"}}, asset_id="L001")
    roster.save({"revision": 2, "lifecycle": {"status": "active"}}, asset_id="L001")
    with pytest.raises(Conflict, match="revision changed"):
        roster.acquire_leases(["L001"], {"L001": 1}, "core-1", 1, "throttle")
    fresh = roster.acquire_leases(["L001"], {"L001": 3}, "core-1", 1, "throttle")[0]
    assert fresh["fencing_token"] > old["fencing_token"]


def test_edit_that_does_not_touch_operating_config_keeps_holds(roster):
    _operating_loco(roster)
    roster.save({"revision": 1, "label": "Cab unit"}, asset_id="L001")
    assert _holds(roster) == (1, 1)


def test_operation_endpoint_reports_holds(tmp_path):
    app = create_app({"DATA_ROOT": str(tmp_path / "data"), "TESTING": True})
    roster = app.extensions["roster"]
    client = app.test_client()
    roster.save(loco(lifecycle={"possession": "received", "status": "active", "location": "main_west_1"}))
    assert client.get("/api/assets/L001/operation").get_json() == {"leased": False, "reserved": False}
    roster.acquire_leases(["L001"], {"L001": 1}, "core-1", 1, "throttle")
    assert client.get("/api/assets/L001/operation").get_json() == {"leased": True, "reserved": False}
    assert client.get("/api/assets/L999/operation").status_code == 404


def test_address_change_retires_lease_but_keeps_reservation_for_stop(roster):
    """STOP must keep targeting the address the decoder is actually answering on."""
    _operating_loco(roster)
    roster.save(
        {"revision": 1, "control": {"dcc": True, "address": 47}}, asset_id="L001"
    )
    assert _holds(roster) == (0, 1)
