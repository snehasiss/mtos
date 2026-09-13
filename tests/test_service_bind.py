"""Bind defaults without opening sockets or touching the live service."""

import importlib.util
import io
import json
from pathlib import Path
import runpy
import sys
from types import SimpleNamespace

import pytest


PROJECT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("action", ["start", "restart"])
@pytest.mark.parametrize("explicit_host", [None, "127.0.0.1"])
def test_service_bind(tmp_path, monkeypatch, capsys, action, explicit_host):
    spec = importlib.util.spec_from_file_location(
        "service", PROJECT / "tools/service.py"
    )
    service = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(service)
    monkeypatch.setattr(service, "data_root", lambda: tmp_path)
    monkeypatch.setattr(service.time, "sleep", lambda _: None)
    monkeypatch.setattr(service.secrets, "token_hex", lambda _: "new")
    state = {"old_running": action == "restart"}
    run = tmp_path / "run"
    run.mkdir()
    if action == "restart":
        (run / "asset_manager.json").write_text(
            json.dumps(
                {"pid": 123, "host": "127.0.0.1", "port": 5301, "instance": "old"}
            )
        )

    def kill(pid, sig):
        assert pid == 123
        state["old_running"] = False

    def launch(command, **kwargs):
        state["command"] = command
        return SimpleNamespace(pid=456, poll=lambda: None)

    def health(url, timeout):
        assert url == "http://127.0.0.1:5301/health"
        if state["old_running"]:
            payload = {"pid": 123, "instance": "old"}
        elif "command" in state:
            payload = {"pid": 456, "instance": "new"}
        else:
            raise OSError("stopped")
        return io.BytesIO(json.dumps(payload).encode())

    monkeypatch.setattr(service.os, "kill", kill)
    monkeypatch.setattr(service.subprocess, "Popen", launch)
    monkeypatch.setattr(service.urllib.request, "urlopen", health)
    monkeypatch.setattr(
        sys,
        "argv",
        ["service.py", action] + (["--host", explicit_host] if explicit_host else []),
    )
    service.main()
    expected = explicit_host or "0.0.0.0"
    command = state["command"]
    assert command[command.index("--host") + 1] == expected
    assert json.loads((run / "asset_manager.json").read_text())["host"] == expected
    assert f"listening on {expected}:5301" in capsys.readouterr().out


@pytest.mark.parametrize("explicit_host", [None, "127.0.0.1"])
def test_direct_server_bind(tmp_path, monkeypatch, explicit_host):
    import mtos.app
    import mtos.roster
    import waitress

    captured = {}
    monkeypatch.setattr(mtos.roster, "data_root", lambda: tmp_path / "data")
    monkeypatch.setattr(mtos.app, "create_app", lambda: "app")
    monkeypatch.setattr(
        waitress, "serve", lambda app, **kwargs: captured.update(kwargs)
    )
    monkeypatch.setattr(
        sys, "argv", ["serve.py"] + (["--host", explicit_host] if explicit_host else [])
    )
    runpy.run_path(str(PROJECT / "tools/serve.py"), run_name="__main__")
    assert captured["host"] == (explicit_host or "0.0.0.0")
    assert captured["port"] == 5301
