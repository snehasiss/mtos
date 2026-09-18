#!/usr/bin/env python3
"""Named MTOS service lifecycle commands."""

import argparse
import fcntl
import json
import os
import secrets
import signal
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from mtos.roster import data_root


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--service",
        choices=["mtos_asset", "asset_manager", "asset_control", "mtos_hmi", "mtos_dcc", "mtos_core"],
        default="mtos_asset",
    )
    parser.add_argument("action", choices=["start", "stop", "restart", "status"])
    parser.add_argument("--host")
    args = parser.parse_args()
    # asset_manager is a compatibility spelling. Canonicalize it so old and new
    # launchers share one lock, pidfile and process and cannot bind port 5301 twice.
    aliases = {"asset_manager": "mtos_asset", "asset_control": "mtos_hmi"}
    args.service = aliases.get(args.service, args.service)
    args.port = {"mtos_asset": 5301, "mtos_hmi": 5302, "mtos_core": 5303, "mtos_dcc": 5304}[args.service]
    if args.host is None:
        args.host = "0.0.0.0" if args.service in ("mtos_asset", "mtos_hmi") else "127.0.0.1"
    run = data_root() / "run"
    run.mkdir(parents=True, exist_ok=True)
    pidfile = run / f"{args.service}.json"

    def running():
        if not pidfile.exists():
            return None
        info = json.loads(pidfile.read_text())
        host = "127.0.0.1" if info["host"] == "0.0.0.0" else info["host"]
        try:
            with urllib.request.urlopen(
                f"http://{host}:{info['port']}/health", timeout=1
            ) as response:
                health = json.load(response)
            return (
                info
                if (
                    health.get("pid") == info["pid"]
                    and health.get("instance") == info.get("instance")
                )
                else None
            )
        except (OSError, ValueError):
            return None

    with (run / f"{args.service}.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        info = running()
        if args.action == "status":
            print(
                f"Running PID {info['pid']} at {info['host']}:{info['port']}"
                if info
                else "Stopped"
            )
            return
        if args.action in ("stop", "restart") and info:
            os.kill(info["pid"], signal.SIGTERM)
            for _ in range(100):
                if not running():
                    break
                time.sleep(0.1)
            else:
                raise RuntimeError("Service did not stop; inspect it before retrying")
            pidfile.unlink(missing_ok=True)
            info = None
            print("Stopped")
        if args.action == "stop":
            return
        if info:
            print(f"Already running PID {info['pid']}")
            return
        instance = secrets.token_hex(16)
        with (run / f"{args.service}.log").open("a") as log:
            process = subprocess.Popen(
                [
                    sys.executable,
                    str(ROOT / "tools/serve.py"),
                    "--host",
                    args.host,
                    "--port",
                    str(args.port),
                    "--service",
                    args.service,
                ],
                cwd=ROOT,
                stdout=log,
                stderr=log,
                start_new_session=True,
                env={**os.environ, "MTOS_INSTANCE": instance},
            )
        host = "127.0.0.1" if args.host == "0.0.0.0" else args.host
        try:
            for _ in range(100):
                if process.poll() is not None:
                    raise RuntimeError(
                        f"Service exited; see {run / (args.service + '.log')}"
                    )
                try:
                    with urllib.request.urlopen(
                        f"http://{host}:{args.port}/health", timeout=0.2
                    ) as response:
                        health = json.load(response)
                        if (
                            health.get("instance") == instance
                            and health.get("pid") == process.pid
                        ):
                            time.sleep(0.1)
                            if process.poll() is not None:
                                raise RuntimeError("Service failed to bind")
                            break
                except (OSError, ValueError):
                    pass
                time.sleep(0.1)
            else:
                raise RuntimeError("Service startup timed out")
        except Exception:
            if process.poll() is None:
                process.terminate()
                process.wait(timeout=10)
            raise
        pidfile.write_text(
            json.dumps(
                {
                    "pid": process.pid,
                    "host": args.host,
                    "port": args.port,
                    "instance": instance,
                }
            )
        )
        print(f"Started PID {process.pid}: listening on {args.host}:{args.port}")


if __name__ == "__main__":
    sys.exit(main())
