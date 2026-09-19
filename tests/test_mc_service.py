import json
from datetime import UTC, datetime, timedelta

import pytest

from mtos.mc.models import ExecutionRequest
from mtos.mc.mqtt import FakeMqttTransport
from mtos.mc.service import McConflict, McService, StaleCoreSession
from mtos.mc_app import create_mc_app


def request(service, eid, asset, node, operation="turnout.set", value="straight", resources=None, fence=1):
    return {
        "command_id": "command-" + eid, "execution_id": eid,
        "core_session_id": "core", "core_epoch": 4,
        "asset_id": asset, "asset_revision": 2, "configuration_revision": 8,
        "lease_id": "lease-" + eid, "fencing_token": fence, "node_id": node,
        "operation": operation, "value": value,
        "resources": resources if resources is not None else (["servo"] if operation == "turnout.set" else []),
        "expires_at": (datetime.now(UTC) + timedelta(minutes=1)).isoformat(),
    }


def ready_node(service, node_id, boot="boot-1"):
    return service.update_node({
        "node_id": node_id, "boot_id": boot, "firmware": "0.1.0",
        "configuration_revision": 8, "producer_session_id": service.session_id,
        "availability": "online",
    })


def event(service, execution, state, result=None):
    item = service.execution(execution)
    node = service.nodes_by_id[item["node_id"]]
    return service.handle_event({
        "execution_id": execution, "node_id": item["node_id"],
        "boot_id": node["boot_id"], "producer_session_id": service.session_id,
        "payload_hash": item["payload_hash"], "state": state, "result": result,
    })


def make_service(tmp_path):
    transport = FakeMqttTransport()
    service = McService(tmp_path / "data", transport, scheduler_interval=None)
    service.establish_core_session("core", 4)
    return service, transport


def test_request_validation_and_hash_are_stable():
    class Service: pass
    value = request(Service(), "e1", "T001", "N001")
    first = ExecutionRequest.from_dict(value)
    second = ExecutionRequest.from_dict(dict(reversed(list(value.items()))))
    assert first.payload_hash == second.payload_hash
    value["value"] = "normal"
    with pytest.raises(ValueError, match="unsupported"):
        ExecutionRequest.from_dict(value)


def test_global_servo_gate_serializes_across_nodes(tmp_path):
    service, transport = make_service(tmp_path)
    ready_node(service, "N001")
    ready_node(service, "N002", "boot-2")
    service.submit(request(service, "e1", "T001", "N001"))
    service.submit(request(service, "e2", "T002", "N002"))
    assert service.run_once() is True
    assert service.servo_execution == "e1"
    assert service.run_once() is False
    assert len(transport.published) == 1
    for state in ("accepted", "started", "completed"):
        event(service, "e1", state)
    assert service.servo_execution is None
    assert service.run_once() is True
    assert service.servo_execution == "e2"
    assert len(transport.published) == 2


def test_signal_does_not_consume_servo_and_duplicate_is_idempotent(tmp_path):
    service, transport = make_service(tmp_path)
    ready_node(service, "N001")
    servo = request(service, "e1", "T001", "N001")
    signal = request(service, "e2", "G001", "N001", "signal.set", "stop", [])
    assert service.submit(servo)["replayed"] is False
    assert service.submit(servo)["replayed"] is True
    service.submit(signal)
    service.run_once()
    assert service.servo_execution == "e1"
    service.run_once()
    assert len(transport.published) == 2
    assert service.servo_execution == "e1"
    changed = dict(servo, value="diverging")
    with pytest.raises(ValueError, match="reused"):
        service.submit(changed)


def test_uncertain_servo_blocks_until_supervised_reconciliation(tmp_path):
    service, _ = make_service(tmp_path)
    ready_node(service, "N001")
    ready_node(service, "N002", "boot-2")
    service.submit(request(service, "e1", "T001", "N001"))
    service.submit(request(service, "e2", "T002", "N002"))
    service.run_once()
    event(service, "e1", "accepted")
    event(service, "e1", "started")
    service.update_node({"node_id": "N001", "boot_id": "new-boot", "firmware": "0.1.0", "configuration_revision": 8, "producer_session_id": service.session_id, "availability": "online"})
    assert service.execution("e1")["state"] == "uncertain"
    assert service.run_once() is False
    service.reconcile("e1", "failed", "physical inspection")
    assert service.run_once() is True


def test_fencing_core_watchdog_machine_resource_and_api(tmp_path):
    service, _ = make_service(tmp_path)
    ready_node(service, "N001")
    machine = request(service, "m1", "E001", "N001", "machine.execute", "operate", ["machine"], 3)
    assert service.submit(machine)["state"] == "queued"
    stale = request(service, "m2", "E001", "N001", "machine.execute", "operate", ["machine"], 2)
    stale["command_id"] = "other"
    with pytest.raises((StaleCoreSession, McConflict)):
        service.submit(stale)

    app = create_mc_app({"TESTING": True, "INTERNAL_TOKEN": "secret", "MC_SERVICE": service})
    client = app.test_client()
    headers = {"X-MTOS-Internal-Token": "secret"}
    assert client.get("/health").json["service"] == "mtos_mc"
    assert client.get("/v1/state").status_code == 403
    assert client.get("/v1/state", headers=headers).json["broker"] == "connected"
    assert client.get("/v1/nodes", headers=headers).json["items"][0]["node_id"] == "N001"
    assert client.get("/v1/executions/m1", headers=headers).json["state"] == "queued"


def test_mqtt_topic_validation_and_event_identity(tmp_path):
    service, _ = make_service(tmp_path)
    status = {"node_id": "N001", "boot_id": "boot", "firmware": "0.1.0", "configuration_revision": 8, "producer_session_id": service.session_id, "availability": "online"}
    service.handle_mqtt("mtos/v1/nodes/N001/status", json.dumps(status).encode())
    service.submit(request(service, "e1", "T001", "N001"))
    service.run_once()
    item = service.execution("e1")
    accepted = {"node_id": "N001", "boot_id": "boot", "producer_session_id": service.session_id, "execution_id": "e1", "payload_hash": item["payload_hash"], "state": "accepted"}
    assert service.handle_mqtt("mtos/v1/nodes/N001/events", json.dumps(accepted).encode())["state"] == "accepted"
    accepted["boot_id"] = "wrong"
    with pytest.raises(McConflict):
        service.handle_mqtt("mtos/v1/nodes/N001/events", json.dumps(accepted).encode())


def test_signals_are_serialized_per_node_but_parallel_across_nodes(tmp_path):
    service, transport = make_service(tmp_path)
    ready_node(service, "N001")
    ready_node(service, "N002", "boot-2")
    for eid, asset, node in (("s1", "G001", "N001"), ("s2", "G002", "N001"), ("s3", "G003", "N002")):
        service.submit(request(service, eid, asset, node, "signal.set", "go", []))
    assert service.run_once() is True
    assert service.run_once() is True  # N001 is occupied, so N002 may proceed.
    assert len(transport.published) == 2
    assert service.execution("s2")["state"] == "queued"
    for state in ("accepted", "started", "completed"):
        event(service, "s1", state)
    assert service.run_once() is True
    assert len(transport.published) == 3


def test_stale_core_watchdog_prevents_dispatch(tmp_path):
    now = [100.0]
    transport = FakeMqttTransport()
    service = McService(tmp_path / "data", transport, clock=lambda: now[0],
                        heartbeat_timeout=5.0, scheduler_interval=None)
    service.establish_core_session("core", 4)
    ready_node(service, "N001")
    service.submit(request(service, "e1", "T001", "N001"))
    now[0] += 6.0
    assert service.run_once() is False
    assert service.snapshot()["core"]["stale"] is True
    assert service.execution("e1")["state"] == "queued"
    assert transport.published == []


def test_incompatible_firmware_never_becomes_ready(tmp_path):
    service, _ = make_service(tmp_path)
    node = ready_node(service, "N001")
    assert node["ready"] is True
    node = ready_node(service, "N001", "boot-1") | {"firmware": "1.0.0"}
    node = service.update_node(node)
    assert node["ready"] is False


def test_node_session_handshake_supplies_offline_clock_baseline(tmp_path):
    service, transport = make_service(tmp_path)
    service.update_node({
        "node_id": "N001", "boot_id": "boot-1", "firmware": "0.1.0",
        "configuration_revision": 8, "producer_session_id": "old-session",
        "availability": "online",
    })
    topic, encoded, qos, retained = transport.published[-1]
    payload = json.loads(encoded)
    assert topic == "mtos/v1/nodes/N001/commands"
    assert payload["schema"] == "mtos.mc-session.v1"
    assert payload["producer_session_id"] == service.session_id
    assert payload["server_unix_ms"] > 1_700_000_000_000
    assert (qos, retained) == (1, False)


def test_restart_marks_dispatched_servo_uncertain_and_holds_gate(tmp_path):
    service, transport = make_service(tmp_path)
    ready_node(service, "N001")
    service.submit(request(service, "e1", "T001", "N001"))
    assert service.run_once() is True
    service.close()

    restarted = McService(tmp_path / "data", FakeMqttTransport(), scheduler_interval=None)
    assert restarted.execution("e1")["state"] == "uncertain"
    assert restarted.servo_execution == "e1"
    restarted.establish_core_session("new-core", 5)
    ready_node(restarted, "N002", "boot-2")
    second = request(restarted, "e2", "T002", "N002")
    second.update(core_session_id="new-core", core_epoch=5)
    restarted.submit(second)
    assert restarted.run_once() is False
