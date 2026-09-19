#!/usr/bin/env python3
import argparse
import fcntl
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from waitress import serve

from mtos.roster import data_root

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--host")
    parser.add_argument("--port", type=int, default=5301)
    parser.add_argument(
        "--service",
        choices=("mtos_asset", "asset_manager", "asset_control", "mtos_hmi", "mtos_dcc", "mtos_core", "mtos_mc"),
        default="mtos_asset",
    )
    args = parser.parse_args()
    if args.host is None:
        args.host = "0.0.0.0" if args.service in ("mtos_asset", "asset_manager", "asset_control", "mtos_hmi") else "127.0.0.1"
    socketio = None
    if args.service == "asset_control":
        from mtos.control_app import create_control_app

        app = create_control_app()
    elif args.service == "mtos_hmi":
        from mtos.hmi_app import create_hmi_app

        app, socketio = create_hmi_app()
    elif args.service == "mtos_dcc":
        from mtos.dcc_app import create_dcc_app

        app = create_dcc_app()
    elif args.service == "mtos_core":
        from mtos.core_app import create_core_app

        app = create_core_app()
    elif args.service == "mtos_mc":
        from mtos.mc_app import create_mc_app

        app = create_mc_app()
    else:
        from mtos.asset_app import create_asset_app

        app = create_asset_app()
    root = data_root()
    root.parent.mkdir(parents=True, exist_ok=True)
    # Shared lifetime lock: restoration takes the exclusive lock before replacing data.
    with (root.parent / f".{root.name}.services.lock").open("a") as lifetime:
        fcntl.flock(lifetime, fcntl.LOCK_SH)
        if socketio is not None:
            socketio.run(
                app, host=args.host, port=args.port,
                allow_unsafe_werkzeug=True, use_reloader=False,
            )
        else:
            serve(app, host=args.host, port=args.port, threads=4)
