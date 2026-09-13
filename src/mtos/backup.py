"""Manually invoked, verified snapshots of the database and media."""

import argparse
import fcntl
import hashlib
import json
import shutil
import sqlite3
import tempfile
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

from .roster import Roster, data_root


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def verify(snapshot):
    snapshot = Path(snapshot).resolve()
    manifest = json.loads((snapshot / "manifest.json").read_text())
    for name, checksum in manifest["files"].items():
        path = (snapshot / name).resolve()
        if (
            not path.is_relative_to(snapshot)
            or path.is_symlink()
            or not path.is_file()
            or digest(path) != checksum
        ):
            raise ValueError(f"Backup integrity check failed: {name}")
    database = snapshot / "db/mtos.sqlite3"
    with sqlite3.connect(database.as_uri() + "?mode=ro", uri=True) as db:
        if (
            db.execute("PRAGMA integrity_check").fetchone()[0] != "ok"
            or db.execute("PRAGMA foreign_key_check").fetchall()
        ):
            raise ValueError("Backup database integrity check failed")
        for aid, filename, checksum in db.execute(
            "SELECT asset_id,filename,sha256 FROM media"
        ):
            name = f"media/{aid}/{filename}"
            if manifest["files"].get(name) != checksum:
                raise ValueError(f"Media does not match database: {name}")
    return manifest


def backup(roster, remote):
    remote = Path(remote).expanduser().resolve()
    if not remote.is_dir():
        raise ValueError(
            "Backup destination must already exist; check that the drive is mounted"
        )
    if remote.is_relative_to(roster.root) or roster.root.is_relative_to(remote):
        raise ValueError("Backup destination must be outside the live data tree")
    with tempfile.TemporaryDirectory(prefix=".mtos-backup-", dir=remote) as staging:
        stage = Path(staging)
        (stage / "db").mkdir()
        with roster.lock(), roster.connect() as source:
            with sqlite3.connect(stage / "db/mtos.sqlite3") as destination:
                source.backup(destination)
            shutil.copytree(roster.media, stage / "media")
        files = {
            str(p.relative_to(stage)): digest(p)
            for p in stage.rglob("*")
            if p.is_file()
        }
        manifest = {
            "version": 1,
            "created_at": datetime.now(UTC).isoformat(),
            "files": files,
        }
        (stage / "manifest.json").write_text(json.dumps(manifest, indent=2))
        verify(stage)
        name = datetime.now(UTC).strftime("mtos-%Y%m%dT%H%M%S-%fZ")
        target = remote / name
        stage.rename(target)
    return target


def restore(snapshot, destination):
    snapshot = Path(snapshot).expanduser().resolve()
    destination = Path(destination).expanduser().resolve()
    if destination.exists():
        raise ValueError(
            "Restore destination must not exist; restore into a new data directory"
        )
    manifest = verify(snapshot)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix=".mtos-restore-", dir=destination.parent
    ) as staging:
        stage = Path(staging)
        for name in manifest["files"]:
            target = stage / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(snapshot / name, target)
        shutil.copyfile(snapshot / "manifest.json", stage / "manifest.json")
        verify(stage)
        (stage / "manifest.json").unlink()
        stage.rename(destination)
    return destination


def select_snapshot(remote):
    remote = Path(remote).expanduser().resolve()
    if (remote / "manifest.json").is_file():
        return remote
    if not remote.is_dir():
        raise ValueError("Backup directory does not exist; check the mounted drive")
    snapshots = sorted(
        p
        for p in remote.glob("mtos-*")
        if p.is_dir() and (p / "manifest.json").is_file()
    )
    if not snapshots:
        raise ValueError("No completed backup snapshots found")
    return snapshots[-1]


def restore_current(snapshot, destination):
    """Replace stopped service data only after verification; retain the previous tree."""
    destination = Path(destination).expanduser().resolve()
    snapshot = Path(snapshot).expanduser().resolve()
    if snapshot.is_relative_to(destination) or destination.is_relative_to(snapshot):
        raise ValueError("Restore source must be outside the live data tree")
    destination.parent.mkdir(parents=True, exist_ok=True)
    lifetime = destination.parent / f".{destination.name}.services.lock"
    with lifetime.open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise ValueError(
                "Stop asset_manager and asset_control before restoring"
            ) from error
        # Earlier service versions did not hold the lifetime lock. Check their PID state too.
        for state in (destination / "run").glob("*.json"):
            info = json.loads(state.read_text())
            if "host" not in info or "port" not in info:
                continue
            host = "127.0.0.1" if info["host"] == "0.0.0.0" else info["host"]
            try:
                with urllib.request.urlopen(
                    f"http://{host}:{info['port']}/health", timeout=1
                ) as response:
                    healthy = response.status == 200
            except OSError:
                healthy = False
            if healthy:
                raise ValueError(
                    f"Stop the service on port {info['port']} before restoring"
                )
        if not destination.exists():
            return restore(snapshot, destination), None
        # CLI image imports use this same lock; no MTOS write can overlap replacement.
        with (destination / ".lock").open("a") as data_lock:
            fcntl.flock(data_lock, fcntl.LOCK_EX)
            with tempfile.TemporaryDirectory(
                prefix=".mtos-restore-", dir=destination.parent
            ) as temporary:
                prepared = restore(snapshot, Path(temporary) / "data")
                previous = destination.with_name(
                    destination.name
                    + ".before-restore-"
                    + datetime.now(UTC).strftime("%Y%m%dT%H%M%S-%fZ")
                )
                destination.rename(previous)
                try:
                    prepared.rename(destination)
                except Exception:
                    previous.rename(destination)
                    raise
        return destination, previous


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--remote",
        type=Path,
        required=True,
        help="existing mounted backup directory, or snapshot for restore/verify",
    )
    parser.add_argument("--data-dir", type=Path, default=data_root())
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "--backup", action="store_true", help="create a verified snapshot"
    )
    mode.add_argument(
        "--restore",
        action="store_true",
        help="restore the newest snapshot and preserve current data",
    )
    mode.add_argument("--verify", action="store_true")
    parser.add_argument(
        "--restore-to",
        type=Path,
        help="optional new directory instead of replacing live data",
    )
    args = parser.parse_args()
    if args.restore_to and not args.restore:
        parser.error("--restore-to requires --restore")
    try:
        if args.verify:
            verify(select_snapshot(args.remote))
            print("Backup verified")
        elif args.restore:
            snapshot = select_snapshot(args.remote)
            if args.restore_to:
                print(restore(snapshot, args.restore_to))
            else:
                destination, previous = restore_current(snapshot, args.data_dir)
                print(f"Restored {snapshot} to {destination}")
                if previous:
                    print(f"Previous data preserved at {previous}")
        else:
            if not (args.data_dir / "db/mtos.sqlite3").is_file():
                raise ValueError("No live roster database found")
            print(backup(Roster(args.data_dir), args.remote))
    except (OSError, ValueError, sqlite3.Error) as error:
        parser.exit(1, f"Backup failed: {error}\n")
