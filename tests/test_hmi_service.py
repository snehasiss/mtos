from mtos.hmi.service import HmiRejected, HmiService
from mtos.hmi_app import create_hmi_app

import pytest
import time


class FakeGateway:
    def __init__(self):
        self.calls = []
        self.value = {
            "generation": "g1",
            "emergency_latched": False,
            "device": {
                "connection": "ready", "session_id": "device", "port": "/dev/fake",
                "identity": "DCC-EX", "firmware": "5.6.3", "last_seen": None,
                "stale": False, "main": {"letter": "A", "mode": "MAIN", "power": "on"},
                "error": None, "locomotives": {},
            },
        }

    def snapshot(self):
        return self.value

    def locomotives(self):
        return [{"id": "L001", "reporting_mark": "UP", "road_number": "28",
                 "prototype": "8500 GTEL", "address": 28}]

    def devices(self):
        return [{"selection_id": "fake", "port": "/dev/fake", "description": "Fake",
                 "manufacturer": None, "vid": None, "pid": None, "serial_number": None}]

    def command(self, operation, payload, command_id):
        self.calls.append((operation, payload, command_id))
        return {"outcome": "confirmed", "operation": operation}


def command(sequence=0, command_id="c1"):
    return {"command_id": command_id, "client_seq": sequence,
            "operation": "throttle", "payload": {"asset_id": "L001", "speed": 4}}


def test_hmi_bounds_sequences_and_emits_results():
    gateway = FakeGateway()
    service = HmiService(gateway, max_clients=1)
    app, socketio = create_hmi_app({"TESTING": True, "HMI_MONITOR": False, "HMI_SERVICE": service})
    browser = socketio.test_client(app)
    assert browser.is_connected()
    initial = browser.get_received()
    assert initial[0]["name"] == "control.snapshot"
    assert initial[0]["args"][0]["generation"] == "g1"
    rejected = socketio.test_client(app)
    assert not rejected.is_connected()

    ack = browser.emit("control.command", command(), callback=True)
    assert ack == {"accepted": True, "command_id": "c1", "state": "accepted"}
    received = []
    for _ in range(20):
        received.extend(browser.get_received())
        if any(item["name"] == "command.event" and item["args"][0]["event"] == "command.completed" for item in received):
            break
        time.sleep(0.01)
    events = [item["args"][0] for item in received if item["name"] == "command.event"]
    assert [item["event"] for item in events] == ["command.accepted", "command.completed"]
    assert gateway.calls == [("throttle", {"asset_id": "L001", "speed": 4}, "c1")]
    duplicate = browser.emit("control.command", command(), callback=True)
    assert duplicate["accepted"] is False and "client_seq" in duplicate["error"]
    browser.disconnect()


def test_hmi_http_and_request_events():
    gateway = FakeGateway()
    service = HmiService(gateway)
    app, socketio = create_hmi_app({"TESTING": True, "HMI_MONITOR": False, "HMI_SERVICE": service})
    http = app.test_client()
    assert http.get("/health").json["service"] == "mtos_hmi"
    assert http.get("/ready").json["ready"] is True
    assert b'id="root"' in http.get("/").data
    browser = socketio.test_client(app)
    browser.get_received()
    assert browser.emit("roster.request", callback=True)["items"][0]["id"] == "L001"
    assert browser.emit("devices.request", callback=True)["items"][0]["selection_id"] == "fake"


def test_hmi_rejects_oversized_command():
    service = HmiService(FakeGateway())
    service.connect("browser")
    with pytest.raises(HmiRejected, match="16 KiB"):
        service.accept("browser", {
            "command_id": "large", "client_seq": 0, "operation": "x",
            "payload": {"value": "x" * (17 * 1024)},
        })
