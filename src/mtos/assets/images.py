"""Directory import and image optimization for asset media."""

from __future__ import annotations

import re
import sqlite3
import tempfile
from dataclasses import dataclass
from pathlib import Path

MAX_IMAGE_SIZE = (1280, 720)
JPEG_QUALITY = 85


@dataclass(frozen=True, slots=True)
class ImportResult:
    imported: tuple[Path, ...]
    skipped: tuple[Path, ...]
    rejected: tuple[tuple[Path, str], ...] = ()


def read_identities(database: Path) -> list[tuple[str, str | None, str | None]]:
    """Read the asset/prototype identity projection without creating a database."""
    database = database.expanduser().resolve()
    if not database.is_file():
        raise FileNotFoundError(f"roster database is not initialized: {database}")
    connection = sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)
    try:
        return connection.execute(
            "SELECT a.id, p.reporting_mark, p.road_number FROM asset a "
            "LEFT JOIN prototype p ON p.asset_id = a.id"
        ).fetchall()
    finally:
        connection.close()


def import_roster_directory(
    source_dir: Path,
    *,
    identities: list[tuple[str, str | None, str | None]],
    media_root: Path,
    writer=None,
) -> ImportResult:
    """Resolve direct asset IDs or unique prototype identities for a whole scan."""
    source_dir = source_dir.expanduser().resolve()
    if not source_dir.is_dir():
        raise NotADirectoryError(f"image import directory not found: {source_dir}")
    aliases: dict[str, set[str]] = {}
    for asset_id, mark, number in identities:
        if not re.fullmatch(r"[A-Z][0-9]{3}", asset_id):
            raise ValueError(f"invalid roster asset ID: {asset_id}")
        aliases.setdefault(asset_id.casefold(), set()).add(asset_id)
        if mark and number:
            aliases.setdefault(f"{mark}{number}".casefold(), set()).add(asset_id)
    imported, skipped, rejected = [], [], []
    for source in sorted(source_dir.iterdir()):
        if not source.is_file() or source.suffix.lower() != ".jpg":
            continue
        match = re.fullmatch(r"(.+)_([1-9][0-9]*)\.jpg", source.name, re.IGNORECASE)
        targets = aliases.get(match[1].casefold(), set()) if match else set()
        if len(targets) != 1:
            rejected.append(
                (
                    source,
                    "ambiguous identity"
                    if targets
                    else "unknown identity or invalid filename",
                )
            )
            continue
        asset_id = next(iter(targets))
        destination = (
            media_root.expanduser().resolve() / asset_id / f"{asset_id}_{match[2]}.jpg"
        )
        if writer is not None:
            try:
                created = writer(asset_id, int(match[2]), source, optimize=True)
                (imported if created else skipped).append(destination)
            except (OSError, ValueError) as error:
                rejected.append((source, str(error)))
            continue
        if destination.exists():
            skipped.append(destination)
            continue
        destination.parent.mkdir(parents=True, exist_ok=True)
        try:
            optimize_image(source, destination)
        except OSError as error:
            rejected.append((source, str(error)))
        else:
            imported.append(destination)
    return ImportResult(tuple(imported), tuple(skipped), tuple(rejected))


def optimize_image(source: Path, destination: Path) -> None:
    """Atomically create an optimized JPEG inside the 1280x720 boundary."""
    from PIL import Image, ImageOps

    temporary_name: str | None = None
    try:
        with Image.open(source) as opened:
            image = ImageOps.exif_transpose(opened)
            if image.mode in ("RGBA", "LA") or "transparency" in image.info:
                rgba = image.convert("RGBA")
                image = Image.new("RGB", rgba.size, "white")
                image.paste(rgba, mask=rgba.getchannel("A"))
            elif image.mode != "RGB":
                image = image.convert("RGB")
            image.thumbnail(MAX_IMAGE_SIZE, Image.Resampling.LANCZOS)
            with tempfile.NamedTemporaryFile(
                prefix=f".{destination.stem}_",
                suffix=".jpg",
                dir=destination.parent,
                delete=False,
            ) as temporary:
                temporary_name = temporary.name
            image.save(
                temporary_name,
                format="JPEG",
                quality=JPEG_QUALITY,
                optimize=True,
                progressive=True,
            )
        Path(temporary_name).replace(destination)
    except Exception:
        if temporary_name is not None:
            Path(temporary_name).unlink(missing_ok=True)
        raise
