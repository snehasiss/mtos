"""Bounded browser sessions and typed intent projection to Core."""

from __future__ import annotations

import json
import threading
import uuid
from collections import deque


class HmiRejected(RuntimeError):
    pass


class HmiService:
    def __init__(self, gateway, *, max_clients=8, max_outstanding=32):
        self.gateway = gateway
        self.max_clients = max_clients
        self.max_outstanding = max_outstanding
        self.control_session_id = str(uuid.uuid4())
        self._lock = threading.RLock()
        self._clients: dict[str, dict] = {}
        self._event_seq = 0
        self._events = deque(maxlen=1024)

    def connect(self, socket_id):
        with self._lock:
            if socket_id not in self._clients and len(self._clients) >= self.max_clients:
                return False
            self._clients[socket_id] = {"client_seq": -1, "outstanding": set()}
        return True

    def disconnect(self, socket_id):
        with self._lock:
            self._clients.pop(socket_id, None)

    def snapshot(self):
        value = self.gateway.snapshot()
        return {"event": "control.snapshot", "control_session_id": self.control_session_id,
                "event_seq": self._event_seq, **value}

    def locomotives(self):
        return self.gateway.locomotives()

    def devices(self):
        return self.gateway.devices()

    def stationary(self):
        return self.gateway.stationary()

    def programming_assets(self):
        return self.gateway.programming_assets()

    def accept(self, socket_id, command):
        encoded = json.dumps(command, separators=(",", ":")).encode()
        if len(encoded) > 16 * 1024:
            raise HmiRejected("command exceeds 16 KiB")
        command_id = command.get("command_id")
        client_seq = command.get("client_seq")
        operation = command.get("operation")
        payload = command.get("payload")
        if not isinstance(command_id, str) or not command_id:
            raise HmiRejected("command_id required")
        if type(client_seq) is not int or client_seq < 0:
            raise HmiRejected("non-negative client_seq required")
        if not isinstance(operation, str) or not isinstance(payload, dict):
            raise HmiRejected("operation and payload object required")
        with self._lock:
            client = self._clients.get(socket_id)
            if client is None:
                raise HmiRejected("browser session is not registered")
            if client_seq <= client["client_seq"]:
                raise HmiRejected("client_seq must increase")
            if len(client["outstanding"]) >= self.max_outstanding:
                raise HmiRejected("too many unacknowledged commands")
            client["client_seq"] = client_seq
            client["outstanding"].add(command_id)
        return {"command_id": command_id, "operation": operation, "payload": payload}

    def execute(self, socket_id, accepted):
        try:
            result = self.gateway.command(
                accepted["operation"], accepted["payload"], accepted["command_id"]
            )
            kind = "command.queued" if result.get("state") == "queued" else "command.completed"
            return self.event(kind, accepted["command_id"], result=result)
        except Exception as error:
            return self.event("command.failed", accepted["command_id"], error=str(error))
        finally:
            with self._lock:
                client = self._clients.get(socket_id)
                if client:
                    client["outstanding"].discard(accepted["command_id"])

    def event(self, kind, command_id=None, **data):
        with self._lock:
            self._event_seq += 1
            value = {"event": kind, "control_session_id": self.control_session_id,
                     "event_seq": self._event_seq, "command_id": command_id, **data}
            self._events.append(value)
            return value
