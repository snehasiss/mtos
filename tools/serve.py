#!/usr/bin/env python3
import argparse
import fcntl
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from waitress import serve

from mtos.app import create_app
from mtos.roster import data_root

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=5301)
    args = parser.parse_args()
    root = data_root()
    root.parent.mkdir(parents=True, exist_ok=True)
    # Shared lifetime lock: restoration takes the exclusive lock before replacing data.
    with (root.parent / f".{root.name}.services.lock").open("a") as lifetime:
        fcntl.flock(lifetime, fcntl.LOCK_SH)
        serve(create_app(), host=args.host, port=args.port, threads=4)
