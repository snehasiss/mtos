from mtos.control.models import CommandResult, ConnectionState, DeviceState, OutputState, PowerState
from mtos.dcc.service import DccService, StaleCoreSession
from mtos.dcc_app import create_dcc_app

import pytest


class FakeStation:
    def __init__(self):
        self.state = DeviceState(
            connection=ConnectionState.READY,
            session_id="device",
            stale=False,
            main=OutputState(letter="A", mode="MAIN", power=PowerState.ON),
        )
        self.emergencies = 0
        self.calls = []

    def snapshot(self):
        return self.state.to_dict()

    def connect(self, port):
        self.calls.append(("connect", port))
        return self.snapshot()

    def disconnect(self):
        self.calls.append(("disconnect",))
        return self.snapshot()

    def set_main_power(self, on):
        self.calls.append(("power", on))
        return CommandResult("confirmed", "main_power", requested={"on": on})

    def throttle(self, address, speed, direction):
        self.calls.append(("throttle", address, speed, direction))
        return CommandResult("confirmed", "throttle", requested={"speed": speed, "direction": direction})

    def function(self, address, number, active):
        self.calls.append(("function", address, number, active))
        return CommandResult("accepted_unverified", "function")

    def stop(self, address, direction):
        self.calls.append(("stop", address, direction))
        return CommandResult("confirmed", "stop")

    def emergency_stop(self):
        self.emergencies += 1
        return CommandResult("accepted_unverified", "emergency_stop")


def envelope(**extra):
    return {"core_session_id": "core-1", "core_epoch": 1,
            "asset_id": "L001", "fencing_token": 4, **extra}


def test_dcc_session_fencing_and_watchdog_stop():
    now = [10.0]
    station = FakeStation()
    service = DccService(station, clock=lambda: now[0], heartbeat_timeout=6, watchdog_interval=None)
    service.establish_core_session("core-1", 1)
    result = service.execute(envelope(), "throttle", lambda: station.throttle(28, 5, "forward"))
    assert result["outcome"] == "confirmed"
    with pytest.raises(StaleCoreSession):
        service.execute({**envelope(), "fencing_token": 3}, "throttle", lambda: None)
    now[0] = 17.0
    assert service.check_watchdog() is True
    assert station.emergencies == 1
    assert service.check_watchdog() is False
    with pytest.raises(StaleCoreSession, match="stale"):
        service.validate(envelope())
    service.heartbeat("core-1", 1)
    assert service.snapshot()["core"]["stale"] is False
    with pytest.raises(StaleCoreSession):
        service.establish_core_session("other", 1)


def test_dcc_loopback_api_contract():
    station = FakeStation()
    service = DccService(station, watchdog_interval=None)
    app = create_dcc_app({"TESTING": True, "INTERNAL_TOKEN": "secret", "DCC_SERVICE": service})
    client = app.test_client()
    headers = {"X-MTOS-Internal-Token": "secret"}
    assert client.get("/health").json["service"] == "mtos_dcc"
    assert client.get("/ready").status_code == 503
    assert client.post("/v1/core/session", json={"session_id": "core-1", "epoch": 1}).status_code == 403
    assert client.post("/v1/core/session", headers=headers, json={"session_id": "core-1", "epoch": 1}).status_code == 200
    response = client.post(
        "/v1/locomotives/28/throttle", headers=headers,
        json=envelope(speed=9, direction="forward"),
    )
    assert response.status_code == 200
    assert station.calls[-1] == ("throttle", 28, 9, "forward")
    assert client.post("/v1/emergency-stop", headers=headers, json={}).status_code == 200
    assert station.emergencies == 1
