#!/usr/bin/env python3
"""Copy legacy inventory and optimized photos into the MTOS roster."""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from mtos.legacy import migrate
from mtos.roster import Roster, data_root

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source", type=Path, required=True, help="legacy data directory"
    )
    parser.add_argument(
        "--photos", type=Path, required=True, help="legacy optimized photo directory"
    )
    parser.add_argument("--data-dir", type=Path, default=data_root())
    args = parser.parse_args()
    report = migrate(
        Roster(args.data_dir), args.source.expanduser(), args.photos.expanduser()
    )
    print(json.dumps(report, indent=2))
    sys.exit(bool(report["errors"]))
