"""Serialized service, remote-data, and checkout administration."""

from __future__ import annotations

import fcntl
import re
import shutil
import sqlite3
import subprocess
import threading
import uuid
from datetime import UTC, datetime
from pathlib import Path


SERVICES = ("mtos_asset", "mtos_dcc", "mtos_mc", "mtos_core", "mtos_hmi")
REMOTE = re.compile(r"^(?P<host>[A-Za-z0-9_.-]+@[A-Za-z0-9_.-]+):(?P<path>/[A-Za-z0-9_./-]+)$")


class AdminBusy(RuntimeError):
    pass


class AdminService:
    def __init__(self, project_root, data_dir, *, backup_remote=None, runner=None):
        self.project_root = Path(project_root).resolve()
        self.data_dir = Path(data_dir).resolve()
        self.runner = runner or subprocess.run
        self.backup_remote = backup_remote
        self._lock = threading.Lock()
        self._jobs = {}

    def status(self):
        items = []
        for name in SERVICES:
            result = self._run([str(self.project_root / "tools/service.py"), "--service", name, "status"], check=False)
            output = (result.stdout or "").strip()
            items.append({"name": name, "running": result.returncode == 0 and output.startswith("Running"), "detail": output or "Stopped"})
        origin = self._run(["git", "remote", "get-url", "origin"], cwd=self.project_root, check=False)
        return {"admin": "running", "services": items, "running": sum(item["running"] for item in items),
                "backup_remote": self.backup_remote, "git_origin": (origin.stdout or "").strip() if origin.returncode == 0 else None}

    def submit(self, operation, payload):
        if not self._lock.acquire(blocking=False):
            raise AdminBusy("Another administrative operation is still running")
        job_id = str(uuid.uuid4())
        self._jobs[job_id] = {"job_id": job_id, "operation": operation, "state": "running", "detail": "Accepted"}

        def work():
            try:
                detail = self._execute(operation, payload)
                self._jobs[job_id].update(state="completed", detail=detail)
            except Exception as error:
                self._jobs[job_id].update(state="failed", detail=str(error))
            finally:
                self._lock.release()

        threading.Thread(target=work, name=f"mtos-admin-{operation}", daemon=True).start()
        return dict(self._jobs[job_id])

    def job(self, job_id):
        if job_id not in self._jobs:
            raise KeyError(job_id)
        return dict(self._jobs[job_id])

    def _execute(self, operation, payload):
        if operation in {"start", "stop", "restart"}:
            self._run([str(self.project_root / "tools/mtos_services"), operation])
            return f"{operation.title()} all completed"
        if operation == "backup":
            self._require_stopped()
            return self._backup(self.backup_remote)
        if operation == "restore":
            self._require_stopped()
            return self._restore(self.backup_remote)
        if operation == "update":
            self._require_stopped()
            return self._update()
        raise ValueError("Unsupported administrative operation")

    def _require_stopped(self):
        running = [item["name"] for item in self.status()["services"] if item["running"]]
        if running:
            raise RuntimeError("Stop all application services first: " + ", ".join(running))

    @staticmethod
    def _remote(value):
        if not value:
            raise ValueError("MTOS_BACKUP_REMOTE is not configured")
        match = REMOTE.fullmatch(value)
        if not match:
            raise ValueError("Remote must be user@host:/absolute/path")
        return match["host"], match["path"].rstrip("/")

    def _ssh(self, host, *command):
        return self._run(["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8", host, *command])

    def _backup(self, remote):
        host, path = self._remote(remote)
        if not self.data_dir.is_dir():
            raise RuntimeError("Live data directory does not exist")
        self._ssh(host, "mkdir", "-p", f"{path}/data")
        self._run(["rsync", "--archive", "--delete", "-e", "ssh -o BatchMode=yes -o ConnectTimeout=8",
                   str(self.data_dir) + "/", f"{host}:{path}/data/"])
        return f"Complete data directory synchronized to {host}:{path}/data/"

    def _restore(self, remote):
        host, path = self._remote(remote)
        parent = self.data_dir.parent
        stage = parent / f".data.remote-restore-{uuid.uuid4().hex}"
        previous = self.data_dir.with_name(
            self.data_dir.name + ".before-restore-" + datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        )
        stage.mkdir(parents=True)
        try:
            self._ssh(host, "test", "-d", f"{path}/data")
            self._run(["rsync", "--archive", "--delete", "-e", "ssh -o BatchMode=yes -o ConnectTimeout=8",
                       f"{host}:{path}/data/", str(stage) + "/"])
            self._verify_data(stage)
            lifetime = parent / f".{self.data_dir.name}.services.lock"
            with lifetime.open("a") as lock:
                try:
                    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError as error:
                    raise RuntimeError("An MTOS service still owns the data directory") from error
                had_current = self.data_dir.exists()
                if had_current:
                    self.data_dir.rename(previous)
                try:
                    stage.rename(self.data_dir)
                except Exception:
                    if had_current:
                        previous.rename(self.data_dir)
                    raise
            if had_current:
                return f"Remote data restored; previous data preserved at {previous}"
            return "Remote data restored into a new local data directory"
        finally:
            if stage.exists():
                shutil.rmtree(stage)

    @staticmethod
    def _verify_data(root):
        databases = list((root / "db").glob("*.sqlite3"))
        if not any(path.name in {"asset.sqlite3", "mtos.sqlite3"} for path in databases):
            raise RuntimeError("Remote backup has no Asset database")
        for path in databases:
            with sqlite3.connect(path) as database:
                if database.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                    raise RuntimeError(f"Database integrity check failed: {path.name}")

    def _update(self):
        dirty = self._run(["git", "status", "--porcelain"], cwd=self.project_root).stdout.strip()
        if dirty:
            raise RuntimeError("Checkout has local changes; update refused")
        self._run(["git", "fetch", "--prune", "origin"], cwd=self.project_root)
        self._run(["git", "checkout", "main"], cwd=self.project_root)
        self._run(["git", "pull", "--ff-only", "origin", "main"], cwd=self.project_root)
        revision = self._run(["git", "rev-parse", "--short", "HEAD"], cwd=self.project_root).stdout.strip()
        return f"Checked out main at {revision}; no commit created"

    def _run(self, command, *, cwd=None, check=True):
        result = self.runner(command, cwd=cwd or self.project_root, text=True, capture_output=True)
        if check and result.returncode:
            raise RuntimeError((result.stderr or result.stdout or "Command failed").strip())
        return result
