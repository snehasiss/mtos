#!/usr/bin/env python3
"""Scan a directory and resolve image identities against the MTOS roster."""

from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from mtos.roster import Roster  # noqa: E402


def ensure_pillow(parser: argparse.ArgumentParser) -> None:
    """Use the installed project environment before opening any roster data."""
    try:
        from PIL import Image  # noqa: F401
    except ImportError:
        environment = PROJECT_ROOT / ".venv"
        python = environment / "bin/python3"
        if Path(sys.prefix).resolve() != environment.resolve() and python.is_file():
            # Preserve arguments and cwd, including relative --data-dir paths.
            os.execv(
                str(python), [str(python), str(Path(__file__).resolve()), *sys.argv[1:]]
            )
        parser.exit(
            1,
            "Import failed: Pillow is unavailable. Install MTOS dependencies from "
            "the project root:\n"
            "  python3 -m venv .venv\n"
            "  .venv/bin/python -m pip install -e .\n"
            "Then rerun the import command. No photos were imported.\n",
        )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Import conventionally named JPG, JPEG or PNG images as optimized JPEGs."
    )
    parser.add_argument("--source", required=True, type=Path, help="directory to scan")
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=PROJECT_ROOT / "data",
        help="optional data directory override (default: project_root/data)",
    )
    args = parser.parse_args()
    ensure_pillow(parser)
    from mtos.assets.images import import_roster_directory, read_identities

    try:
        roster = Roster(args.data_dir)
        result = import_roster_directory(
            args.source,
            identities=read_identities(roster.database),
            media_root=roster.media,
            writer=roster.put_media,
        )
    except (OSError, ValueError, sqlite3.Error) as error:
        parser.exit(1, f"Import failed: {error}\n")
    for path in result.imported:
        print(f"imported {path}")
    for path in result.skipped:
        print(f"skipped  {path}")
    for path, reason in result.rejected:
        print(f"rejected {path.name}: {reason}")
    print(f"{len(result.imported)} imported, {len(result.skipped)} previously imported")
    if result.rejected:
        parser.exit(1, f"{len(result.rejected)} files need attention\n")


if __name__ == "__main__":
    main()
