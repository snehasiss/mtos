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
