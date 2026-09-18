import json
import re
import threading
import time

import pytest

from mtos.control.dcc.protocol import (
    Framer,
    encode_function,
    encode_main_power,
    encode_throttle,
    parse_frame,
)
from mtos.control.dcc.station import DccExStation
from mtos.control.service import ControlService
from mtos.control_app import create_control_app
from mtos.roster import Conflict, Roster


class FakeSerial:
    def __init__(self, chunks=None):
        self.chunks = list(chunks or [])
        self.writes = []
        self.is_open = False

    def open(self, port, baud_rate, timeout, write_timeout):
        self.port = port
        self.is_open = True

    def read(self, size=1):
        return self.chunks.pop(0) if self.chunks else b""

    def write(self, data):
        self.writes.append(data.decode())
        if data == b"<s>":
            self.chunks.append(b"noise<iDCC-EX V-5.6.3>")
        elif data == b"<=>":
            self.chunks.append(b"<= A MAIN>")
        elif data == b"<1 MAIN>":
            self.chunks.append(b"<p1 MAIN>")
        elif data == b"<0 MAIN>":
            self.chunks.append(b"<p0 MAIN>")
        elif data.startswith(b"<t "):
            parts = data.decode()[1:-1].split()
            address, speed, forward = map(int, parts[1:])
            speed_byte = (129 + speed if speed else 128) if forward else (1 + speed if speed else 0)
            self.chunks.append(f"<l {address} 0 {speed_byte} 0>".encode())

    def close(self):
        self.is_open = False


def active_loco():
    return {
        "id": "L001",
        "family": "loco",
        "type": "diesel",
        "prototype": {"reporting_mark": "UP", "road_number": "28", "model": "8500_gtel"},
        "control": {"dcc": True, "address": 28},
        "lifecycle": {"possession": "received", "status": "active", "location": "test_main_1"},
    }


def test_protocol_validation_framing_and_reports():
    framer = Framer()
    assert framer.feed(b"junk<p1 MA") == []
    assert framer.feed(b"IN><l 28 0 141 3>") == ["<p1 MAIN>", "<l 28 0 141 3>"]
    assert parse_frame("<p1 MAIN>").data == {"state": "on", "scope": "MAIN"}
    loco = parse_frame("<l 28 0 141 3>").data
    assert (loco["speed"], loco["direction"]) == (12, "forward")
    assert loco["functions"] == {str(i): i in (0, 1) for i in range(16)}
    assert encode_main_power(True) == "<1 MAIN>"
    assert encode_throttle(28, 12, "forward") == "<t 28 12 1>"
    assert encode_function(28, 68, True) == "<F 28 68 1>"
    with pytest.raises(ValueError):
        encode_throttle(28, True, "forward")


def test_station_handshake_main_power_throttle_and_disconnect():
    serial = FakeSerial()
    station = DccExStation(serial, response_timeout=0.01, handshake_timeout=0.05)
    assert station.connect("/dev/fake")["connection"] == "ready"
    assert station.state.main.mode == "MAIN"
    assert station.set_main_power(True).outcome == "confirmed"
    result = station.throttle(28, 12, "forward")
    assert result.outcome == "confirmed"
    assert station.state.locomotives["28"].speed == 12
    station.function(28, 32, True)
    assert station.snapshot()["locomotives"]["28"]["desired_functions"]["32"] is True
    station.function(28, 32, False)
    assert station.snapshot()["locomotives"]["28"]["desired_functions"]["32"] is False
    station.emergency_stop()
    assert serial.writes[-1] == "<!>"
    assert station.disconnect()["main"]["power"] == "unknown"


def test_emergency_write_does_not_wait_for_normal_response():
    serial = FakeSerial()
    station = DccExStation(serial, response_timeout=0.2, handshake_timeout=0.05)
    station.connect("/dev/fake")
    station.set_main_power(True)
    original = serial.write

    def no_throttle_response(data):
        if data.startswith(b"<t "):
            serial.writes.append(data.decode())
        else:
            original(data)

    serial.write = no_throttle_response
    worker = threading.Thread(target=lambda: station.throttle(28, 12, "forward"))
    worker.start()
    time.sleep(0.02)
    station.emergency_stop()
    assert serial.writes[-1] == "<!>"
    assert worker.is_alive()
    worker.join()
    station.disconnect()


def test_service_roster_reservation_and_control_edit_guard(tmp_path):
    roster = Roster(tmp_path / "data")
    roster.save(active_loco())
    serial = FakeSerial()
    station = DccExStation(serial, response_timeout=0.01, handshake_timeout=0.05)
    station.connect("/dev/fake")
    station.set_main_power(True)
    service = ControlService(tmp_path / "data", station)
    result = service.throttle("L001", 8, "forward", service.generation)
    assert result["outcome"] == "confirmed"
    with pytest.raises(Conflict, match="reserved"):
        roster.save({"revision": 1, "control": {"address": 29}}, asset_id="L001")
    updated = roster.save({"revision": 1, "label": "Turbine"}, asset_id="L001")
    assert updated["label"] == "Turbine"
    stopped = service.stop("L001")
    assert stopped["generation"] != ""
    service.release("L001")


class FakeControlService(ControlService):
    def devices(self):
        return [{"selection_id": "fake", "port": "/dev/fake", "description": "Fake", "manufacturer": None, "vid": None, "pid": None, "serial_number": None}]


def test_control_flask_api_and_ui(tmp_path):
    roster = Roster(tmp_path / "data")
    roster.save(active_loco())
    inactive = active_loco()
    inactive.update(id="L002", revision=None)
    inactive["prototype"] = {**inactive["prototype"], "road_number": "29"}
    inactive["control"] = {**inactive["control"], "address": 29}
    inactive["lifecycle"] = {**inactive["lifecycle"], "status": "stored"}
    inactive.pop("revision")
    roster.save(inactive)
    service = FakeControlService(
        tmp_path / "data",
        DccExStation(FakeSerial(), response_timeout=0.01, handshake_timeout=0.05),
    )
    app = create_control_app({"TESTING": True, "DATA_ROOT": tmp_path / "data", "CONTROL_SERVICE": service})
    client = app.test_client()
    page = client.get("/")
    assert page.status_code == 200
    assert b'id="root"' in page.data
    script_path = re.search(rb'src="(/control-ui/assets/[^"]+\.js)"', page.data)
    style_path = re.search(rb'href="(/control-ui/assets/[^"]+\.css)"', page.data)
    assert script_path and style_path
    script = client.get(script_path.group(1).decode())
    style = client.get(style_path.group(1).decode())
    assert b"Headlight" in script.data and b"Programming" in script.data
    assert b"function-grid" in style.data
    assert client.get("/health").json["service"] == "asset_control"
    locomotives = client.get("/api/locomotives").json["items"]
    assert [item["id"] for item in locomotives] == ["L001"]
    assert client.post("/api/device/connect", json={"selection_id": "fake"}).status_code == 403
    token = client.get("/api/session").json["csrf"]
    headers = {"X-CSRF-Token": token}
    assert client.post("/api/device/connect", json={"selection_id": "fake"}, headers=headers).status_code == 200
    generation = client.get("/api/control").json["generation"]
    assert client.post("/api/main/power", json={"on": True, "generation": generation}, headers=headers).json["outcome"] == "confirmed"
    response = client.post("/api/locomotives/L001/throttle", json={"speed": 6, "direction": "forward", "generation": generation}, headers=headers)
    assert response.status_code == 200 and response.json["asset_id"] == "L001"
    response = client.post(
        "/api/locomotives/L001/functions/32",
        json={"active": True, "generation": generation},
        headers=headers,
    )
    assert response.status_code == 200
    state = client.get("/api/control").json
    assert state["device"]["locomotives"]["28"]["desired_functions"]["32"] is True
    assert client.post("/api/emergency-stop", json={}, headers=headers).status_code == 200
    assert client.post("/api/locomotives/L001/throttle", json={"speed": 7, "direction": "forward", "generation": generation}, headers=headers).status_code == 409


def test_schema_v5_and_wal(tmp_path):
    roster = Roster(tmp_path / "data")
    with roster.connect() as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 5
        assert db.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
        names = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"control_command", "control_reservation"} <= names
