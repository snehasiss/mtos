"""Directory import and image optimization for asset media."""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from ..image_optimizer import optimize_image


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
            "SELECT a.id, a.family, p.reporting_mark, p.road_number FROM asset a "
            "LEFT JOIN prototype p ON p.asset_id = a.id"
        ).fetchall()
    finally:
        connection.close()


def import_roster_directory(
    source_dir: Path,
    *,
    identities: list[tuple[str, str, str | None, str | None]],
    media_root: Path,
    writer=None,
) -> ImportResult:
    """Resolve direct asset IDs or unique prototype identities for a whole scan."""
    source_dir = source_dir.expanduser().resolve()
    if not source_dir.is_dir():
        raise NotADirectoryError(f"image import directory not found: {source_dir}")
    aliases: dict[str, set[str]] = {}
    families: dict[str, str] = {}
    for asset_id, family, mark, number in identities:
        if not re.fullmatch(r"[A-Z][0-9]{3}", asset_id):
            raise ValueError(f"invalid roster asset ID: {asset_id}")
        aliases.setdefault(asset_id.casefold(), set()).add(asset_id)
        families[asset_id] = family
        if mark and number:
            aliases.setdefault(f"{mark}{number}".casefold(), set()).add(asset_id)
    imported, skipped, rejected = [], [], []
    for source in sorted(source_dir.iterdir()):
        if not source.is_file() or source.suffix.lower() not in {
            ".jpg",
            ".jpeg",
            ".png",
        }:
            continue
        match = re.fullmatch(
            r"(.+)_([1-9][0-9]*)\.(?:jpg|jpeg|png)", source.name, re.IGNORECASE
        )
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
            media_root.expanduser().resolve()
            / families[asset_id]
            / f"{asset_id}_{match[2]}.jpg"
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
