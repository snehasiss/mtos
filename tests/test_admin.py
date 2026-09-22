import sqlite3
import subprocess
import shutil
import time
from pathlib import Path

import pytest

from mtos.admin.service import AdminService
from mtos.admin_app import create_admin_app


class Runner:
    def __init__(self): self.calls = []
    def __call__(self, command, **kwargs):
        self.calls.append(command)
        output = "Stopped\n" if "status" in command else ""
        return subprocess.CompletedProcess(command, 0, output, "")


def test_remote_backup_uses_key_only_ssh_and_rsyncs_complete_data(tmp_path):
    data = tmp_path / "data"; data.mkdir()
    runner = Runner(); service = AdminService(tmp_path, data, runner=runner)
    detail = service._execute("backup", {"remote": "backup@server:/srv/mtos"})
    assert "data directory" in detail
    ssh = next(call for call in runner.calls if call[0] == "ssh")
    rsync = next(call for call in runner.calls if call[0] == "rsync")
    assert "BatchMode=yes" in ssh and ssh[-1] == "/srv/mtos/data"
    assert "--delete" in rsync
    assert rsync[-2] == str(data.resolve()) + "/"
    assert rsync[-1] == "backup@server:/srv/mtos/data/"
    with pytest.raises(ValueError, match="user@host"):
        service._execute("backup", {"remote": str(tmp_path / "local")})


def test_remote_restore_database_validation(tmp_path):
    root = tmp_path / "stage"; (root / "db").mkdir(parents=True)
    with sqlite3.connect(root / "db/asset.sqlite3") as database:
        database.execute("CREATE TABLE asset(id TEXT PRIMARY KEY)")
    AdminService._verify_data(root)
    (root / "db/asset.sqlite3").write_bytes(b"broken")
    with pytest.raises(sqlite3.DatabaseError):
        AdminService._verify_data(root)


def test_remote_restore_can_create_missing_local_data_directory(tmp_path):
    remote = tmp_path / "remote"
    (remote / "db").mkdir(parents=True)
    with sqlite3.connect(remote / "db/asset.sqlite3") as database:
        database.execute("CREATE TABLE asset(id TEXT PRIMARY KEY)")

    def runner(command, **kwargs):
        if command[0] == "rsync":
            shutil.copytree(remote, Path(command[-1].rstrip("/")), dirs_exist_ok=True)
        return subprocess.CompletedProcess(command, 0, "", "")

    data = tmp_path / "live/data"
    service = AdminService(tmp_path, data, runner=runner)
    detail = service._restore("backup@server:/srv/mtos")
    assert detail == "Remote data restored into a new local data directory"
    assert (data / "db/asset.sqlite3").is_file()


class FakeAdmin:
    def status(self): return {"admin": "running", "running": 0, "services": []}
    def submit(self, operation, payload): return {"job_id": "j1", "operation": operation, "state": "running"}
    def job(self, job_id): return {"job_id": job_id, "state": "completed", "detail": "done"}


def test_admin_ui_auth_csrf_and_job_contract(tmp_path):
    app = create_admin_app({"TESTING": True, "ADMIN_TOKEN": "secret", "SECRET_KEY": "session",
                            "ADMIN_SERVICE": FakeAdmin(), "PROJECT_ROOT": tmp_path, "DATA_ROOT": tmp_path / "data"})
    client = app.test_client()
    assert client.get("/health").json["service"] == "mtos_admin"
    page = client.get("/")
    assert b"mtos-logo-wireframe.png" in page.data and b"Remote data continuity" in page.data
    assert client.get("/api/status").status_code == 401
    assert client.post("/api/login", json={"token": "wrong"}).status_code == 403
    login = client.post("/api/login", json={"token": "secret"}).json
    assert client.get("/api/status").status_code == 200
    assert client.post("/api/actions/stop", json={}).status_code == 403
    accepted = client.post("/api/actions/stop", json={}, headers={"X-CSRF-Token": login["csrf"]})
    assert accepted.status_code == 202 and accepted.json["job_id"] == "j1"
    assert client.get("/api/jobs/j1").json["state"] == "completed"
