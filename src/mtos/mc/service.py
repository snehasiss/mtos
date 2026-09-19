"""Fenced MQTT accessory execution with global servo exclusion."""

from __future__ import annotations

import json
import threading
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from .models import ExecutionRequest, TERMINAL
from .mqtt import OfflineMqttTransport
from .repository import McRepository


class McBusy(RuntimeError): pass
class McConflict(RuntimeError): pass
class StaleCoreSession(RuntimeError): pass


SUPPORTED_FIRMWARE_PREFIX = "0."


@dataclass
class CoreSession:
    session_id: str
    epoch: int
    last_heartbeat: float
    stale: bool = False


class McService:
    def __init__(self, data_root, transport=None, *, clock=time.monotonic,
                 heartbeat_timeout=6.0, node_timeout=15.0, capacity=256,
                 scheduler_interval=0.1):
        self.repository = McRepository(data_root)
        self.transport = transport or OfflineMqttTransport()
        self.clock = clock
        self.heartbeat_timeout = heartbeat_timeout
        self.node_timeout = node_timeout
        self.capacity = capacity
        self.session_id = str(uuid.uuid4())
        self.epoch = self.repository.next_epoch()
        self.core = None
        self.nodes_by_id = {}
        self.servo_execution = None
        self.machine_execution = None
        self.signal_nodes = {}
        self.actuator_nodes = {}
        self._lock = threading.RLock()
        self._shutdown = threading.Event()
        self._thread = None
        for execution in self.repository.nonterminal():
            if execution["state"] not in {"queued", "uncertain"}:
                execution = self.repository.transition(execution["execution_id"], "uncertain", {"reason": "mc_restart"})
            resources = set(execution["payload"].get("resources") or [])
            if execution["state"] == "uncertain" and "servo" in resources:
                self.servo_execution = execution["execution_id"]
            if execution["state"] == "uncertain" and "machine" in resources:
                self.machine_execution = execution["execution_id"]
            if execution["state"] == "uncertain" and resources & {"servo", "machine"}:
                self.actuator_nodes[execution["node_id"]] = execution["execution_id"]
        if scheduler_interval is not None:
            self._thread = threading.Thread(target=self._loop, args=(scheduler_interval,), name="mtos-mc-scheduler", daemon=True)
            self._thread.start()

    def establish_core_session(self, session_id, epoch):
        if not session_id or type(epoch) is not int or epoch < 1:
            raise ValueError("valid Core session and epoch required")
        with self._lock:
            if self.core and epoch <= self.core.epoch and session_id != self.core.session_id:
                raise StaleCoreSession("Core epoch must increase")
            self.core = CoreSession(session_id, epoch, self.clock())
        return self.snapshot()["core"]

    def heartbeat(self, session_id, epoch):
        with self._lock:
            self._require_core(session_id, epoch, allow_stale=True)
            self.core.last_heartbeat = self.clock()
            self.core.stale = False
        return self.snapshot()["core"]

    def check_watchdog(self):
        with self._lock:
            if self.core and not self.core.stale and self.clock() - self.core.last_heartbeat > self.heartbeat_timeout:
                self.core.stale = True
                return True
        return False

    def snapshot(self):
        self.check_watchdog()
        self._refresh_nodes()
        core = None if not self.core else {"session_id": self.core.session_id, "epoch": self.core.epoch, "stale": self.core.stale}
        return {"session_id": self.session_id, "epoch": self.epoch, "core": core,
                "broker": "connected" if self.transport.connected else "offline",
                "servo_gate": self.servo_execution, "machine_gate": self.machine_execution,
                "nodes": self.nodes(), "executions": self.repository.recent()}

    def nodes(self):
        return [dict(value) for _, value in sorted(self.nodes_by_id.items())]

    def update_node(self, value):
        node_id = value.get("node_id")
        if not isinstance(node_id, str) or not node_id:
            raise ValueError("node_id required")
        existing = self.nodes_by_id.get(node_id)
        boot_id = value.get("boot_id")
        if existing and existing.get("boot_id") and boot_id != existing["boot_id"]:
            for execution in self.repository.nonterminal():
                if execution["node_id"] == node_id and execution["state"] != "queued":
                    self._uncertain(execution["execution_id"], "node_reboot")
        node = {"node_id": node_id, "boot_id": boot_id, "firmware": value.get("firmware"),
                "configuration_revision": value.get("configuration_revision"),
                "producer_session_id": value.get("producer_session_id"),
                "availability": value.get("availability", "online"),
                "last_seen": self.clock(), "detail": value.get("detail") or {}}
        node["ready"] = self._node_ready(node)
        self.nodes_by_id[node_id] = node
        self.repository.save_node(node)
        if self.transport.connected and node.get("availability") == "online" and node.get("producer_session_id") != self.session_id:
            message = {"schema": "mtos.mc-session.v1", "node_id": node_id,
                       "boot_id": boot_id, "producer_session_id": self.session_id,
                       "mc_epoch": self.epoch,
                       "server_unix_ms": int(time.time() * 1000)}
            self.transport.publish(f"mtos/v1/nodes/{node_id}/commands",
                                   json.dumps(message, separators=(",", ":")).encode(), qos=1, retain=False)
        return dict(node)

    def handle_mqtt(self, topic, payload):
        try:
            value = json.loads(payload)
        except (TypeError, ValueError) as error:
            raise ValueError("invalid MQTT JSON payload") from error
        parts = topic.split("/")
        if len(parts) != 5 or parts[:3] != ["mtos", "v1", "nodes"]:
            raise ValueError("unexpected MQTT topic")
        node_id, kind = parts[3], parts[4]
        if value.get("node_id") not in (None, node_id):
            raise ValueError("topic node and payload node differ")
        value["node_id"] = node_id
        if kind == "events":
            return self.handle_event(value)
        if kind == "availability":
            existing = self.nodes_by_id.get(node_id, {"node_id": node_id})
            existing.update(value)
            return self.update_node(existing)
        if kind == "status":
            return self.update_node(value)
        raise ValueError("unsupported MQTT topic")

    def submit(self, value):
        request = ExecutionRequest.from_dict(value)
        with self._lock:
            self._require_core(request.core_session_id, request.core_epoch)
            if len(self.repository.nonterminal()) >= self.capacity:
                raise McBusy("MC execution capacity reached")
            if not self.repository.check_and_advance_fence(request.asset_id, request.fencing_token):
                raise StaleCoreSession("stale asset fencing token")
            for item in self.repository.nonterminal():
                if item["asset_id"] == request.asset_id and item["execution_id"] != request.execution_id:
                    raise McConflict("asset already has a non-terminal execution")
            execution, replayed = self.repository.insert(request)
            execution["replayed"] = replayed
            return execution

    def run_once(self):
        self.check_watchdog()
        if not self.core or self.core.stale or not self.transport.connected:
            return False
        for execution in self.repository.queued():
            payload = execution["payload"]
            if datetime.fromisoformat(payload["expires_at"]) <= datetime.now(UTC):
                self.repository.transition(execution["execution_id"], "expired", {"reason": "expired_before_dispatch"})
                continue
            node = self.nodes_by_id.get(execution["node_id"])
            if not node or not self._node_ready(node) or node.get("configuration_revision") != payload["configuration_revision"]:
                continue
            resources = set(payload.get("resources") or [])
            if "servo" in resources and self.servo_execution:
                continue
            if "machine" in resources and self.machine_execution:
                continue
            if resources & {"servo", "machine"} and execution["node_id"] in self.actuator_nodes:
                continue
            if execution["operation"] == "signal.set" and execution["node_id"] in self.signal_nodes:
                continue
            if "servo" in resources: self.servo_execution = execution["execution_id"]
            if "machine" in resources: self.machine_execution = execution["execution_id"]
            if resources & {"servo", "machine"}: self.actuator_nodes[execution["node_id"]] = execution["execution_id"]
            if execution["operation"] == "signal.set": self.signal_nodes[execution["node_id"]] = execution["execution_id"]
            command = {"schema": "mtos.mc-command.v1", "payload_hash": execution["payload_hash"],
                       "producer_session_id": self.session_id, "boot_id": node["boot_id"], **payload}
            command["expires_unix_ms"] = int(datetime.fromisoformat(payload["expires_at"]).timestamp() * 1000)
            self.repository.transition(execution["execution_id"], "dispatched")
            try:
                self.transport.publish(f"mtos/v1/nodes/{execution['node_id']}/commands",
                                       json.dumps(command, separators=(",", ":")).encode(), qos=1, retain=False)
            except Exception as error:
                self._uncertain(execution["execution_id"], "publish_unknown", str(error))
                raise
            return True
        return False

    def handle_event(self, value):
        execution = self.repository.get(value.get("execution_id"))
        payload = execution["payload"]
        node = self.nodes_by_id.get(execution["node_id"])
        if not node or value.get("node_id") != execution["node_id"] or value.get("boot_id") != node.get("boot_id") or value.get("producer_session_id") != self.session_id or value.get("payload_hash") != execution["payload_hash"]:
            raise McConflict("event identity/session does not match execution")
        state = value.get("state")
        allowed = {"dispatched": {"accepted", "rejected", "failed"}, "accepted": {"started", "failed"}, "started": {"completed", "failed", "uncertain"}}
        if execution["state"] in TERMINAL:
            return execution
        if state not in allowed.get(execution["state"], set()):
            raise McConflict("invalid or regressive event transition")
        if state == "uncertain":
            return self._uncertain(execution["execution_id"], "node_reported_uncertain")
        updated = self.repository.transition(execution["execution_id"], state, value.get("result"))
        if state in TERMINAL:
            self._release(execution["execution_id"], payload)
        return updated

    def cancel(self, execution_id):
        execution = self.repository.get(execution_id)
        if execution["state"] != "queued":
            raise McConflict("only queued execution can be cancelled")
        return self.repository.transition(execution_id, "cancelled")

    def reconcile(self, execution_id, resolution, detail=None):
        execution = self.repository.get(execution_id)
        if execution["state"] != "uncertain" or resolution not in {"completed", "failed"}:
            raise McConflict("uncertain execution requires completed or failed resolution")
        updated = self.repository.transition(execution_id, resolution, {"reconciled": True, "detail": detail})
        self._release(execution_id, execution["payload"])
        return updated

    def execution(self, execution_id): return self.repository.get(execution_id)

    def close(self):
        self._shutdown.set()
        if self._thread and self._thread is not threading.current_thread(): self._thread.join(timeout=1)
        self.transport.close()

    def _loop(self, interval):
        while not self._shutdown.wait(interval):
            try: self.run_once()
            except Exception: pass

    def _refresh_nodes(self):
        for node in self.nodes_by_id.values():
            if self.clock() - node["last_seen"] > self.node_timeout:
                node["availability"] = "stale"
            node["ready"] = self._node_ready(node)

    def _node_ready(self, node):
        return (node.get("availability") == "online" and bool(node.get("boot_id"))
                and isinstance(node.get("firmware"), str)
                and node["firmware"].startswith(SUPPORTED_FIRMWARE_PREFIX)
                and type(node.get("configuration_revision")) is int
                and node.get("producer_session_id") == self.session_id
                and self.clock() - node.get("last_seen", 0) <= self.node_timeout)

    def _uncertain(self, execution_id, reason, detail=None):
        execution = self.repository.transition(execution_id, "uncertain", {"reason": reason, "detail": detail})
        resources = set(execution["payload"].get("resources") or [])
        if "servo" in resources: self.servo_execution = execution_id
        if "machine" in resources: self.machine_execution = execution_id
        if resources & {"servo", "machine"}: self.actuator_nodes[execution["node_id"]] = execution_id
        if execution["operation"] == "signal.set": self.signal_nodes[execution["node_id"]] = execution_id
        return execution

    def _release(self, execution_id, payload):
        resources = set(payload.get("resources") or [])
        if "servo" in resources and self.servo_execution == execution_id: self.servo_execution = None
        if "machine" in resources and self.machine_execution == execution_id: self.machine_execution = None
        node_id = payload["node_id"]
        if self.actuator_nodes.get(node_id) == execution_id: self.actuator_nodes.pop(node_id, None)
        if self.signal_nodes.get(node_id) == execution_id: self.signal_nodes.pop(node_id, None)

    def _require_core(self, session_id, epoch, allow_stale=False):
        if not self.core or session_id != self.core.session_id or epoch != self.core.epoch:
            raise StaleCoreSession("unknown or stale Core session")
        if self.core.stale and not allow_stale:
            raise StaleCoreSession("Core heartbeat is stale")
