import subprocess
import sys
from pathlib import Path

import pytest

pytest.importorskip("PIL")
from PIL import Image

from mtos.assets.images import import_roster_directory, optimize_image


def test_roster_cli(tmp_path: Path) -> None:
    incoming = tmp_path / "incoming"
    incoming.mkdir()
    for name in ("SAL4202_1.jpg", "G013_2.jpg", "UP28_1.jpg"):
        make_image(incoming / name)
    from mtos.roster import Roster

    roster = Roster(tmp_path)
    for aid, mark, number in [
        ("L001", "SAL", "4202"),
        ("L002", "UP", "28"),
        ("L003", "UP", "28"),
    ]:
        roster.save(
            {
                "id": aid,
                "family": "loco",
                "type": "diesel",
                "prototype": {"reporting_mark": mark, "road_number": number},
            }
        )
    roster.save({"id": "G013", "family": "signal", "type": "mainline_3a"})
    command = [
        sys.executable,
        str(Path(__file__).resolve().parents[1] / "tools/import_image.py"),
        "--source",
        str(incoming),
        "--data-dir",
        str(tmp_path),
    ]
    first = subprocess.run(command, capture_output=True, text=True)
    assert first.returncode == 1
    assert "2 imported" in first.stdout
    assert "ambiguous identity" in first.stdout
    assert (tmp_path / "media/L001/L001_1.jpg").exists()
    assert (tmp_path / "media/G013/G013_2.jpg").exists()
    second = subprocess.run(command, capture_output=True, text=True)
    assert "0 imported, 2 previously imported" in second.stdout


def make_image(path: Path, size: tuple[int, int] = (2400, 1600)) -> None:
    Image.new("RGB", size, "red").save(path)


def test_scans_rolling_stock_images_and_preserves_input_sequence(
    tmp_path: Path,
) -> None:
    incoming = tmp_path / "incoming"
    incoming.mkdir()
    make_image(incoming / "SAL4202_1.jpg")
    make_image(incoming / "SAL4202_3.jpg")
    make_image(incoming / "ignore_1.jpg")

    result = import_roster_directory(
        incoming,
        identities=[("L001", "SAL", "4202")],
        media_root=tmp_path / "media",
    )

    assert [path.name for path in result.imported] == ["L001_1.jpg", "L001_3.jpg"]
    assert result.rejected[0][0].name == "ignore_1.jpg"
    with Image.open(result.imported[0]) as image:
        assert image.size == (1080, 720)
        assert image.format == "JPEG"


def test_second_scan_skips_previously_imported_files(tmp_path: Path) -> None:
    incoming = tmp_path / "incoming"
    incoming.mkdir()
    make_image(incoming / "UP28_1.jpg", (640, 480))
    arguments = dict(
        source_dir=incoming,
        identities=[("L028", "UP", "28")],
        media_root=tmp_path / "media",
    )

    first = import_roster_directory(**arguments)
    second = import_roster_directory(**arguments)

    assert len(first.imported) == 1
    assert second.imported == ()
    assert [path.name for path in second.skipped] == ["L028_1.jpg"]


def test_stationary_asset_id_resolves_and_type_only_is_rejected(tmp_path: Path) -> None:
    incoming = tmp_path / "incoming"
    incoming.mkdir()
    make_image(incoming / "G013_1.jpg", (100, 200))
    make_image(incoming / "mainline_3a_2.jpg", (100, 200))

    result = import_roster_directory(
        incoming,
        identities=[("G013", None, None)],
        media_root=tmp_path / "media",
    )

    assert [path.name for path in result.imported] == ["G013_1.jpg"]
    assert len(result.rejected) == 1
    assert result.imported[0].parent.name == "G013"


def test_corrupt_photo_is_reported_without_partial_file(tmp_path: Path) -> None:
    incoming = tmp_path / "incoming"
    incoming.mkdir()
    (incoming / "L001_1.jpg").write_bytes(b"broken")
    result = import_roster_directory(
        incoming, identities=[("L001", None, None)], media_root=tmp_path / "media"
    )
    assert len(result.rejected) == 1
    assert not list((tmp_path / "media").rglob("*.jpg"))


def test_transparent_image_gets_white_background(tmp_path: Path) -> None:
    source = tmp_path / "transparent.png"
    destination = tmp_path / "out.jpg"
    Image.new("RGBA", (20, 20), (0, 0, 0, 0)).save(source)
    optimize_image(source, destination)
    with Image.open(destination) as image:
        assert image.size == (20, 20)
        assert image.getpixel((10, 10)) == (255, 255, 255)
