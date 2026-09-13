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
        "--service", choices=["asset_manager", "asset_control"], default="asset_manager"
    )
    parser.add_argument("action", choices=["start", "stop", "restart", "status"])
    parser.add_argument("--host", default="0.0.0.0")
    args = parser.parse_args()
    args.port = {"asset_manager": 5301, "asset_control": 5302}[args.service]
    if args.service == "asset_control":
        print(
            "asset_control: port 5302 reserved; DCC/electronics control is not implemented yet."
        )
        return 0 if args.action in ("stop", "status") else 1
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
