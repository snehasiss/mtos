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
    assert (tmp_path / "media/loco/L001_1.jpg").exists()
    assert (tmp_path / "media/signal/G013_2.jpg").exists()
    second = subprocess.run(command, capture_output=True, text=True)
    assert "0 imported, 2 previously imported" in second.stdout


def test_cli_missing_pillow_uses_project_environment(tmp_path: Path) -> None:
    project = Path(__file__).resolve().parents[1]
    if not (project / ".venv/bin/python3").is_file():
        pytest.skip("Project virtual environment not installed")
    from mtos.roster import Roster

    incoming = tmp_path / "incoming"
    incoming.mkdir()
    make_image(incoming / "L001_1.jpg")
    Roster(tmp_path / "data").save({"id": "L001", "family": "loco", "type": "diesel"})
    result = subprocess.run(
        [
            str(Path(sys.executable).resolve()),
            "-S",
            str(project / "tools/import_image.py"),
            "--source",
            str(incoming),
            "--data-dir",
            "data/",
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert "1 imported" in result.stdout
    assert (tmp_path / "data/media/loco/L001_1.jpg").is_file()


def test_missing_pillow_without_environment_fails_before_data_access(
    tmp_path, monkeypatch, capsys
):
    import builtins
    import importlib.util

    project = Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location(
        "image_cli", project / "tools/import_image.py"
    )
    cli = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cli)
    original_import = builtins.__import__

    def no_pillow(name, *args, **kwargs):
        if name == "PIL":
            raise ModuleNotFoundError("No module named 'PIL'")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", no_pillow)
    monkeypatch.setattr(cli, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "import_image.py",
            "--source",
            str(tmp_path),
            "--data-dir",
            str(tmp_path / "data"),
        ],
    )
    with pytest.raises(SystemExit) as error:
        cli.main()
    assert error.value.code == 1
    assert "pip install -e ." in capsys.readouterr().err
    assert not (tmp_path / "data").exists()


def make_image(path: Path, size: tuple[int, int] = (2400, 1600)) -> None:
    Image.new("RGB", size, "red").save(path)


@pytest.mark.parametrize("extension", ["jpg", "JPG", "jpeg", "JPEG", "png", "PNG"])
def test_cli_image_formats(tmp_path, extension):
    from mtos.roster import Roster

    incoming = tmp_path / "incoming"
    incoming.mkdir()
    source = incoming / f"UP1111_1.{extension}"
    if extension.lower() == "png":
        Image.new("RGBA", (1600, 800), (0, 0, 0, 0)).save(source)
    else:
        make_image(source, (1600, 800))
    original = source.read_bytes()
    roster = Roster(tmp_path / "data")
    roster.save(
        {
            "id": "L001",
            "family": "loco",
            "type": "diesel",
            "prototype": {"reporting_mark": "UP", "road_number": "1111"},
        }
    )
    command = [
        sys.executable,
        str(Path(__file__).resolve().parents[1] / "tools/import_image.py"),
        "--source",
        str(incoming),
        "--data-dir",
        str(roster.root),
    ]
    result = subprocess.run(command, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    destination = roster.media / "loco/L001_1.jpg"
    with Image.open(destination) as image:
        assert image.format == "JPEG"
        assert image.size == (1280, 720)
        if extension.lower() == "png":
            assert image.getpixel((0, 0)) == (255, 255, 255)
    assert source.read_bytes() == original
    assert roster.get("L001")["media"]["images"][0]["filename"] == "L001_1.jpg"
    repeated = subprocess.run(command, capture_output=True, text=True)
    assert repeated.returncode == 0
    assert "0 imported, 1 previously imported" in repeated.stdout


def test_different_extensions_do_not_overwrite_same_sequence(tmp_path):
    incoming = tmp_path / "incoming"
    incoming.mkdir()
    make_image(incoming / "L001_1.jpeg")
    Image.new("RGB", (20, 20), "blue").save(incoming / "L001_1.png")
    result = import_roster_directory(
        incoming,
        identities=[("L001", "loco", None, None)],
        media_root=tmp_path / "media",
    )
    assert len(result.imported) == 1
    assert len(result.skipped) == 1
    with Image.open(result.imported[0]) as image:
        assert image.size == (1280, 720)


def test_existing_asset_media_directory_migrates_to_family(tmp_path):
    from mtos.roster import Roster

    roster = Roster(tmp_path / "data")
    roster.save({"id": "L001", "family": "loco", "type": "diesel"})
    source = tmp_path / "source.jpg"
    make_image(source, (100, 50))
    roster.put_media("L001", 1, source, optimize=True)
    canonical = roster.media / "loco/L001_1.jpg"
    legacy = roster.media / "L001/L001_1.jpg"
    legacy.parent.mkdir()
    canonical.rename(legacy)

    migrated = Roster(roster.root)
    assert migrated.media_path("L001", "L001_1.jpg") == canonical
    assert canonical.is_file()
    assert not legacy.parent.exists()


def test_family_change_is_rejected_when_media_exists(tmp_path):
    from mtos.roster import Roster

    roster = Roster(tmp_path / "data")
    asset = roster.save({"id": "C001", "family": "freight", "type": "wagon"})
    source = tmp_path / "source.jpg"
    make_image(source)
    roster.put_media("C001", 1, source, optimize=True)
    with pytest.raises(ValueError, match="family cannot change"):
        roster.save(
            {"revision": asset["revision"], "family": "passenger", "type": "coach"},
            asset_id="C001",
        )
    assert roster.get("C001")["family"] == "freight"
    assert (roster.media / "freight/C001_1.jpg").is_file()


def test_cli_defaults_to_project_data_from_another_directory(tmp_path, monkeypatch):
    import importlib.util
    from mtos.roster import Roster

    project = Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location(
        "image_cli", project / "tools/import_image.py"
    )
    cli = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cli)
    fake_project = tmp_path / "project"
    incoming = tmp_path / "incoming"
    incoming.mkdir()
    make_image(incoming / "L001_1.jpg")
    Roster(fake_project / "data").save(
        {"id": "L001", "family": "loco", "type": "diesel"}
    )
    monkeypatch.setattr(cli, "PROJECT_ROOT", fake_project)
    monkeypatch.chdir(incoming)
    monkeypatch.setenv("MTOS_DATA_DIR", str(tmp_path / "other_data"))
    monkeypatch.setattr(sys, "argv", ["import_image.py", "--source", str(incoming)])
    cli.main()
    assert (fake_project / "data/media/loco/L001_1.jpg").is_file()
    assert not (incoming / "data").exists()
    assert not (tmp_path / "other_data").exists()


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
        identities=[("L001", "loco", "SAL", "4202")],
        media_root=tmp_path / "media",
    )

    assert [path.name for path in result.imported] == ["L001_1.jpg", "L001_3.jpg"]
    assert result.rejected[0][0].name == "ignore_1.jpg"
    with Image.open(result.imported[0]) as image:
        assert image.size == (1280, 720)
        assert image.format == "JPEG"


def test_second_scan_skips_previously_imported_files(tmp_path: Path) -> None:
    incoming = tmp_path / "incoming"
    incoming.mkdir()
    make_image(incoming / "UP28_1.jpg", (640, 480))
    arguments = dict(
        source_dir=incoming,
        identities=[("L028", "loco", "UP", "28")],
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
        identities=[("G013", "signal", None, None)],
        media_root=tmp_path / "media",
    )

    assert [path.name for path in result.imported] == ["G013_1.jpg"]
    assert len(result.rejected) == 1
    assert result.imported[0].parent.name == "signal"


def test_corrupt_photo_is_reported_without_partial_file(tmp_path: Path) -> None:
    incoming = tmp_path / "incoming"
    incoming.mkdir()
    (incoming / "L001_1.jpg").write_bytes(b"broken")
    result = import_roster_directory(
        incoming,
        identities=[("L001", "loco", None, None)],
        media_root=tmp_path / "media",
    )
    assert len(result.rejected) == 1
    assert not list((tmp_path / "media").rglob("*.jpg"))


def test_transparent_image_gets_white_background(tmp_path: Path) -> None:
    source = tmp_path / "transparent.png"
    destination = tmp_path / "out.jpg"
    Image.new("RGBA", (20, 20), (0, 0, 0, 0)).save(source)
    optimize_image(source, destination)
    with Image.open(destination) as image:
        assert image.size == (16, 9)
        assert image.getpixel((8, 4)) == (255, 255, 255)


def test_optimizer_center_crops_wide_source_to_sixteen_by_nine(tmp_path: Path) -> None:
    source = tmp_path / "wide.png"
    destination = tmp_path / "out.jpg"
    image = Image.new("RGB", (2000, 900), "red")
    image.paste("blue", (100, 0, 1900, 900))
    image.save(source)

    optimize_image(source, destination)

    with Image.open(destination) as optimized:
        assert optimized.size == (1280, 720)
        assert optimized.getpixel((0, 360))[2] > 200
        assert optimized.getpixel((1279, 360))[2] > 200


def test_optimizer_rejects_image_too_small_without_upscaling(tmp_path: Path) -> None:
    source = tmp_path / "tiny.png"
    destination = tmp_path / "out.jpg"
    Image.new("RGB", (8, 8), "red").save(source)

    with pytest.raises(ValueError, match="at least 16 by 9"):
        optimize_image(source, destination)
    assert not destination.exists()
