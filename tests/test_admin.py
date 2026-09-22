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
        if command[:4] == ["git", "remote", "get-url", "origin"]:
            output = "git@github.com:snehasiss/mtos.git\n"
        elif command[0].endswith("service.py") and "status" in command:
            output = "Stopped\n"
        else:
            output = ""
        return subprocess.CompletedProcess(command, 0, output, "")


def test_remote_backup_uses_key_only_ssh_and_rsyncs_complete_data(tmp_path):
    data = tmp_path / "data"; data.mkdir()
    runner = Runner(); service = AdminService(tmp_path, data, backup_remote="backup@server:/srv/mtos", runner=runner)
    detail = service._execute("backup", {"remote": "other@server:/wrong"})
    assert "data directory" in detail
    ssh = next(call for call in runner.calls if call[0] == "ssh")
    rsync = next(call for call in runner.calls if call[0] == "rsync")
    assert "BatchMode=yes" in ssh and ssh[-1] == "/srv/mtos/data"
    assert "--delete" in rsync
    assert rsync[-2] == str(data.resolve()) + "/"
    assert rsync[-1] == "backup@server:/srv/mtos/data/"
    assert service.status()["backup_remote"] == "backup@server:/srv/mtos"
    assert service.status()["git_origin"] == "git@github.com:snehasiss/mtos.git"
    service.backup_remote = str(tmp_path / "local")
    with pytest.raises(ValueError, match="user@host"):
        service._execute("backup", {})
    service.backup_remote = None
    with pytest.raises(ValueError, match="MTOS_BACKUP_REMOTE"):
        service._execute("backup", {})


def test_update_always_uses_origin_main(tmp_path):
    runner = Runner(); service = AdminService(tmp_path, tmp_path / "data", runner=runner)
    service._execute("update", {"ref": "other-branch"})
    assert ["git", "checkout", "main"] in runner.calls
    assert ["git", "pull", "--ff-only", "origin", "main"] in runner.calls
    assert ["git", "checkout", "other-branch"] not in runner.calls


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
    service = AdminService(tmp_path, data, backup_remote="backup@server:/srv/mtos", runner=runner)
    detail = service._execute("restore", {"remote": "other@server:/wrong"})
    assert detail == "Remote data restored into a new local data directory"
    assert (data / "db/asset.sqlite3").is_file()


class FakeAdmin:
    def status(self): return {"admin": "running", "running": 0, "services": [],
                              "backup_remote": "backup@server:/srv/mtos", "git_origin": "git@github.com:snehasiss/mtos.git"}
    def submit(self, operation, payload): return {"job_id": "j1", "operation": operation, "state": "running"}
    def job(self, job_id): return {"job_id": job_id, "state": "completed", "detail": "done"}


def test_admin_ui_auth_csrf_and_job_contract(tmp_path):
    app = create_admin_app({"TESTING": True, "ADMIN_TOKEN": "secret", "SECRET_KEY": "session",
                            "ADMIN_SERVICE": FakeAdmin(), "PROJECT_ROOT": tmp_path, "DATA_ROOT": tmp_path / "data"})
    client = app.test_client()
    assert client.get("/health").json["service"] == "mtos_admin"
    page = client.get("/")
    assert b"mtos-logo-wireframe.png" in page.data and b"Remote data continuity" in page.data
    assert b'id="remote"' in page.data and b'<input id="remote"' not in page.data
    assert b'id="git-origin"' in page.data and b'<input id="git-ref"' not in page.data
    assert b'id="data-progress"' in page.data and b'id="update-progress"' in page.data
    assert client.get("/api/status").status_code == 401
    assert client.post("/api/login", json={"token": "wrong"}).status_code == 403
    login = client.post("/api/login", json={"token": "secret"}).json
    assert client.get("/api/status").json["backup_remote"] == "backup@server:/srv/mtos"
    assert client.get("/api/status").json["git_origin"] == "git@github.com:snehasiss/mtos.git"
    assert client.post("/api/actions/stop", json={}).status_code == 403
    accepted = client.post("/api/actions/stop", json={}, headers={"X-CSRF-Token": login["csrf"]})
    assert accepted.status_code == 202 and accepted.json["job_id"] == "j1"
    assert client.get("/api/jobs/j1").json["state"] == "completed"


def test_admin_app_reads_fixed_backup_destination(tmp_path):
    remote = "snehasis@mtos-backup:/Users/snehasis/project/backup-cubietruck-mtos-data"
    app = create_admin_app({"TESTING": True, "ADMIN_TOKEN": "secret", "SECRET_KEY": "session",
                            "PROJECT_ROOT": tmp_path, "DATA_ROOT": tmp_path / "data", "BACKUP_REMOTE": remote})
    assert app.extensions["admin_service"].backup_remote == remote
