#!/usr/bin/env python3
"""Scan a directory and resolve image identities against the MTOS roster."""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from mtos.assets.images import import_roster_directory, read_identities  # noqa: E402
from mtos.roster import Roster, data_root  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Import new conventionally named JPEGs from one directory."
    )
    parser.add_argument("--source", required=True, type=Path, help="directory to scan")
    parser.add_argument("--data-dir", type=Path, default=data_root())
    args = parser.parse_args()
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
