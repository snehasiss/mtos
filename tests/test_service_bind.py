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
        (run / "mtos_asset.json").write_text(
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
    assert json.loads((run / "mtos_asset.json").read_text())["host"] == expected
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


def test_asset_manager_name_canonicalizes_to_mtos_asset(tmp_path, monkeypatch, capsys):
    spec = importlib.util.spec_from_file_location(
        "service_alias", PROJECT / "tools/service.py"
    )
    service = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(service)
    monkeypatch.setattr(service, "data_root", lambda: tmp_path)
    monkeypatch.setattr(
        sys, "argv", ["service.py", "--service", "asset_manager", "status"]
    )
    service.main()
    assert "Stopped" in capsys.readouterr().out
    assert (tmp_path / "run/mtos_asset.lock").exists()
    assert not (tmp_path / "run/asset_manager.lock").exists()


def test_asset_control_name_canonicalizes_to_mtos_hmi(tmp_path, monkeypatch, capsys):
    spec = importlib.util.spec_from_file_location(
        "service_hmi_alias", PROJECT / "tools/service.py"
    )
    service = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(service)
    monkeypatch.setattr(service, "data_root", lambda: tmp_path)
    monkeypatch.setattr(
        sys, "argv", ["service.py", "--service", "asset_control", "status"]
    )
    service.main()
    assert "Stopped" in capsys.readouterr().out
    assert (tmp_path / "run/mtos_hmi.lock").exists()
    assert not (tmp_path / "run/asset_control.lock").exists()


def test_admin_service_defaults_to_public_port_5300(tmp_path, monkeypatch, capsys):
    spec = importlib.util.spec_from_file_location(
        "service_admin", PROJECT / "tools/service.py"
    )
    service = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(service)
    monkeypatch.setattr(service, "data_root", lambda: tmp_path)
    monkeypatch.setattr(service.time, "sleep", lambda _: None)
    monkeypatch.setattr(service.secrets, "token_hex", lambda _: "instance")
    state = {}

    def launch(command, **kwargs):
        state["command"] = command
        return SimpleNamespace(pid=456, poll=lambda: None)

    def health(url, timeout):
        assert url == "http://127.0.0.1:5300/health"
        return io.BytesIO(json.dumps({"pid": 456, "instance": "instance"}).encode())

    monkeypatch.setattr(service.subprocess, "Popen", launch)
    monkeypatch.setattr(service.urllib.request, "urlopen", health)
    monkeypatch.setattr(
        sys, "argv", ["service.py", "--service", "mtos_admin", "start"]
    )
    service.main()
    command = state["command"]
    assert command[command.index("--host") + 1] == "0.0.0.0"
    assert command[command.index("--port") + 1] == "5300"
    assert "0.0.0.0:5300" in capsys.readouterr().out


@pytest.mark.parametrize(
    ("service_name", "expected_port"), [("mtos_core", 5303), ("mtos_dcc", 5304)]
)
def test_internal_services_default_to_loopback(
    tmp_path, monkeypatch, capsys, service_name, expected_port
):
    spec = importlib.util.spec_from_file_location(
        f"service_{service_name}", PROJECT / "tools/service.py"
    )
    service = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(service)
    monkeypatch.setattr(service, "data_root", lambda: tmp_path)
    monkeypatch.setattr(service.time, "sleep", lambda _: None)
    monkeypatch.setattr(service.secrets, "token_hex", lambda _: "instance")
    state = {}

    def launch(command, **kwargs):
        state["command"] = command
        return SimpleNamespace(pid=456, poll=lambda: None)

    def health(url, timeout):
        assert url == f"http://127.0.0.1:{expected_port}/health"
        return io.BytesIO(json.dumps({"pid": 456, "instance": "instance"}).encode())

    monkeypatch.setattr(service.subprocess, "Popen", launch)
    monkeypatch.setattr(service.urllib.request, "urlopen", health)
    monkeypatch.setattr(sys, "argv", ["service.py", "--service", service_name, "start"])
    service.main()
    command = state["command"]
    assert command[command.index("--host") + 1] == "127.0.0.1"
    assert command[command.index("--port") + 1] == str(expected_port)
    assert f"127.0.0.1:{expected_port}" in capsys.readouterr().out
