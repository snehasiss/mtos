import sqlite3

from mtos.core.service import CoreService
from mtos.core_app import create_core_app


class FakeAsset:
    def __init__(self):
        self.asset = {
            "id": "L001", "revision": 7, "family": "loco", "type": "diesel",
            "lifecycle": {"possession": "received", "status": "active", "location": "test_main_1"},
            "control": {"dcc": True, "address": 28},
        }
        self.fence = 0

    def get(self, asset_id):
        if asset_id != "L001":
            raise KeyError(asset_id)
        return self.asset

    def acquire_lease(self, asset_id, revision, session_id, epoch, purpose):
        assert revision == 7 and session_id == "core-1" and epoch == 3
        self.fence += 1
        return {"lease_id": f"lease-{self.fence}", "fencing_token": self.fence}

    def locomotives(self):
        return [{"id": "L001", "reporting_mark": "UP", "road_number": "28",
                 "prototype": "8500_gtel", "address": 28}]

    def programming_assets(self):
        return [{"id": "L001", "reporting_mark": "UP", "road_number": "28",
                 "prototype": "8500_gtel", "address": 28, "revision": 7,
                 "status": "maintenance", "location": "test_prog_1"}]

    def update_programmed_address(self, asset_id, revision, address):
        assert asset_id == "L001" and revision == self.asset["revision"]
        self.asset["control"]["address"] = address
        self.asset["revision"] += 1
        return self.asset


class FakeDcc:
    def __init__(self):
        self.calls = []

    def session(self, session_id, epoch):
        self.calls.append(("session", session_id, epoch))
        return {"session_id": session_id, "epoch": epoch}

    def heartbeat(self, session_id, epoch):
        self.calls.append(("heartbeat", session_id, epoch))
        return {"stale": False}

    def command(self, path, envelope):
        self.calls.append((path, envelope))
        return {"outcome": "confirmed", "operation": path.rsplit("/", 1)[-1]}

    def emergency_stop(self):
        self.calls.append(("emergency",))
        return {"outcome": "accepted_unverified", "operation": "emergency_stop"}

    def state(self):
        return {"core": {"stale": False}, "device": {
            "connection": "ready", "session_id": "dcc", "port": "/dev/fake",
            "identity": "DCC-EX", "firmware": None, "last_seen": None, "stale": False,
            "main": {"letter": "A", "mode": "MAIN", "power": "off"},
            "error": None, "locomotives": {},
        }}

    def devices(self):
        return [{"selection_id": "fake", "port": "/dev/fake", "description": "Fake"}]

    def program_address(self, envelope):
        self.calls.append(("program_address", envelope))
        return {"outcome": "confirmed", "operation": "program_address",
                "reported": {"address": envelope["new_address"], "cvs": {1: envelope["new_address"]}}}

    def read_address(self, envelope):
        self.calls.append(("read_address", envelope))
        return {"outcome": "confirmed", "operation": "read_address", "reported": {"address": 28}}

    def read_cv(self, envelope):
        self.calls.append(("read_cv", envelope))
        return {"outcome": "confirmed", "operation": "read_cv", "reported": {"cv": envelope["cv"], "value": 151}}

    def program_cv(self, envelope):
        self.calls.append(("program_cv", envelope))
        return {"outcome": "confirmed", "operation": "program_cv", "reported": {"cv": envelope["cv"], "value": envelope["value"]}}


class FakeMc:
    def __init__(self): self.calls = []; self.executions = []
    def session(self, session_id, epoch): self.calls.append(("session", session_id, epoch)); return {"stale": False}
    def heartbeat(self, session_id, epoch): self.calls.append(("heartbeat", session_id, epoch)); return {"stale": False}
    def state(self): return {"broker": "connected", "nodes": [{"node_id": "N001", "ready": True}], "servo_gate": None, "machine_gate": None, "executions": self.executions}
    def submit(self, envelope): self.calls.append(("submit", envelope)); return {"state": "queued", "execution_id": envelope["execution_id"]}


class FakeStationaryAsset(FakeAsset):
    def __init__(self):
        super().__init__()
        self.asset = {"id": "T001", "revision": 5, "family": "turnout", "type": "left",
                      "lifecycle": {"possession": "received", "status": "active", "location": "yard_south_1"},
                      "control": {"node_id": "N001", "configuration_revision": 8}}
    def get(self, asset_id): return self.asset
    def acquire_lease(self, asset_id, revision, session_id, epoch, purpose):
        self.fence += 1; return {"lease_id": f"lease-{self.fence}", "fencing_token": self.fence}
    def stationary(self): return [{"id": "T001", "family": "turnout", "type": "left", "node_id": "N001"}]


def make_service(tmp_path):
    return CoreService(
        tmp_path / "data", FakeAsset(), FakeDcc(), session_id="core-1", epoch=3,
        heartbeat_interval=None,
    )


def test_core_validates_leases_journals_and_deduplicates(tmp_path):
    service = make_service(tmp_path)
    service.start()
    result = service.throttle("L001", 12, "forward", "command-1")
    assert result["outcome"] == "confirmed"
    path, sent = service.dcc.calls[-1]
    assert path == "/v1/locomotives/28/throttle"
    assert sent["asset_revision"] == 7 and sent["fencing_token"] == 1
    replay = service.throttle("L001", 12, "forward", "command-1")
    assert replay["replayed"] is True
    assert len([c for c in service.dcc.calls if isinstance(c[0], str) and c[0].startswith("/v1/")]) == 1
    with service.repository.connect() as db:
        command = db.execute("SELECT state,outcome FROM command WHERE command_id='command-1'").fetchone()
        reservation = db.execute("SELECT * FROM reservation WHERE asset_id='L001'").fetchone()
    assert tuple(command) == ("completed", "confirmed")
    assert reservation["address"] == 28
    assert service.repository.path.name == "core.sqlite3"
    with sqlite3.connect(service.repository.path) as database:
        assert database.execute("PRAGMA user_version").fetchone()[0] == 1


def test_core_emergency_latch_and_api(tmp_path):
    service = make_service(tmp_path)
    app = create_core_app({"TESTING": True, "INTERNAL_TOKEN": "secret", "CORE_SERVICE": service})
    client = app.test_client()
    headers = {"X-MTOS-Internal-Token": "secret"}
    assert client.get("/health").json["service"] == "mtos_core"
    assert client.get("/ready", headers=headers).status_code == 503
    assert client.post("/v1/start", headers=headers, json={}).status_code == 200
    snapshot = client.get("/v1/hmi/snapshot", headers=headers)
    assert snapshot.status_code == 200 and snapshot.json["device"]["connection"] == "ready"
    assert client.get("/v1/hmi/locomotives", headers=headers).json["items"][0]["id"] == "L001"
    assert client.get("/v1/hmi/devices", headers=headers).json["items"][0]["selection_id"] == "fake"
    connected = client.post(
        "/v1/hmi/commands", headers=headers,
        json={"command_id": "connect-1", "operation": "device.connect",
              "payload": {"selection_id": "fake"}},
    )
    assert connected.status_code == 200
    assert service.dcc.calls[-1][0] == "/v1/device/connect"
    response = client.post("/v1/emergency-stop", headers=headers, json={"command_id": "e1"})
    assert response.status_code == 200 and response.json["emergency_latched"] is True
    blocked = client.post(
        "/v1/locomotives/L001/throttle", headers=headers,
        json={"speed": 2, "direction": "forward"},
    )
    assert blocked.status_code == 409
    assert client.post("/v1/resume", headers=headers, json={}).status_code == 200


def test_core_epoch_increases_across_service_restart(tmp_path):
    first = CoreService(
        tmp_path / "data", FakeAsset(), FakeDcc(), session_id="first",
        heartbeat_interval=None,
    )
    second = CoreService(
        tmp_path / "data", FakeAsset(), FakeDcc(), session_id="second",
        heartbeat_interval=None,
    )
    assert second.epoch == first.epoch + 1


def test_core_programs_then_commits_decoder_address(tmp_path):
    service = make_service(tmp_path)
    service.asset.asset["lifecycle"]["status"] = "maintenance"
    service.asset.asset["lifecycle"]["location"] = "test_prog_1"
    service.start()
    result = service.program_address("L001", 29, "program-1")
    assert result["outcome"] == "confirmed"
    assert result["control_address"] == 29
    assert service.asset.asset["control"]["address"] == 29
    assert service.repository.reservation("L001") is None
    with service.repository.connect() as database:
        row = database.execute(
            "SELECT state,outcome FROM command WHERE command_id='program-1'"
        ).fetchone()
    assert tuple(row) == ("completed", "confirmed")


def test_core_reads_unassigned_address_and_programs_cv_on_prog_track(tmp_path):
    service = make_service(tmp_path)
    service.asset.asset["lifecycle"].update(status="maintenance", location="test_prog_1")
    service.start()
    address = service.read_address(None, "read-address-1")
    assert address["reported"]["address"] == 28
    read = service.read_cv("L001", 8, "read-cv-1")
    assert read["reported"] == {"cv": 8, "value": 151}
    written = service.program_cv("L001", 8, 151, "write-cv-1")
    assert written["reported"] == {"cv": 8, "value": 151}


def test_core_refuses_programming_asset_off_prog_track(tmp_path):
    service = make_service(tmp_path)
    service.asset.asset["lifecycle"]["status"] = "maintenance"
    service.start()
    import pytest
    with pytest.raises(Exception, match="test_prog_1"):
        service.program_address("L001", 29, "wrong-track")


def test_core_records_uncertain_if_asset_commit_fails_after_programming(tmp_path):
    service = make_service(tmp_path)
    service.asset.asset["lifecycle"]["status"] = "maintenance"
    service.asset.asset["lifecycle"]["location"] = "test_prog_1"
    service.start()
    service.asset.update_programmed_address = lambda *_: (_ for _ in ()).throw(
        RuntimeError("asset update failed")
    )
    import pytest
    with pytest.raises(RuntimeError, match="asset update failed"):
        service.program_address("L001", 29, "program-uncertain")
    with service.repository.connect() as database:
        row = database.execute(
            "SELECT state,outcome,result FROM command WHERE command_id='program-uncertain'"
        ).fetchone()
    assert tuple(row[:2]) == ("uncertain", "uncertain")
    assert '"address": 29' in row["result"]
    assert service.repository.reservation("L001")["address"] == 28


def test_core_routes_stationary_intent_to_mc_with_lease_and_resource(tmp_path):
    mc = FakeMc()
    service = CoreService(tmp_path / "data", FakeStationaryAsset(), FakeDcc(), mc,
                          session_id="core-1", epoch=3, heartbeat_interval=None)
    service.start()
    result = service.stationary("turnout.set", "T001", "diverging", "turnout-command")
    assert result["state"] == "queued"
    sent = mc.calls[-1][1]
    assert sent["node_id"] == "N001" and sent["resources"] == ["servo"]
    assert sent["configuration_revision"] == 8 and sent["fencing_token"] == 1
    replay = service.stationary("turnout.set", "T001", "diverging", "turnout-command")
    assert replay["replayed"] is True
    assert len([call for call in mc.calls if call[0] == "submit"]) == 1
    assert service.hmi_snapshot()["mc"]["broker"] == "connected"
    mc.executions = [{"execution_id": result["execution_id"], "asset_id": "T001",
                      "operation": "turnout.set", "state": "completed", "result": {}}]
    service.heartbeat()
    with service.repository.connect() as database:
        row = database.execute("SELECT state,outcome FROM command WHERE command_id='turnout-command'").fetchone()
    assert tuple(row) == ("completed", "completed")
