"""Central operational authority for accepted human or autonomous intent."""

from __future__ import annotations

import threading
import uuid

from .repository import CoreRepository


class CoreConflict(RuntimeError):
    pass


class CoreService:
    def __init__(self, data_root, asset_client, dcc_client, mc_client=None, *, session_id=None, epoch=None,
                 heartbeat_interval=2.0):
        self.repository = CoreRepository(data_root)
        self.asset = asset_client
        self.dcc = dcc_client
        self.mc = mc_client
        self.session_id = session_id or str(uuid.uuid4())
        self.epoch = self.repository.next_epoch() if epoch is None else epoch
        self.started = False
        self.dcc_ready = False
        self.mc_ready = False
        self.last_error = None
        self.emergency_latched = False
        self._lock = threading.RLock()
        self._heartbeat_interval = heartbeat_interval
        self._shutdown = threading.Event()
        self._heartbeat_thread = None

    def start(self):
        self.dcc.session(self.session_id, self.epoch)
        if self.mc:
            self.mc.session(self.session_id, self.epoch)
        self.started = True
        self.dcc_ready = True
        self.mc_ready = self.mc is not None
        self.last_error = None
        if self._heartbeat_interval is not None and not self._heartbeat_thread:
            self._heartbeat_thread = threading.Thread(
                target=self._heartbeat_loop, name="mtos-core-heartbeat", daemon=True
            )
            self._heartbeat_thread.start()
        return self.snapshot()

    def heartbeat(self):
        self._require_started()
        result = self.dcc.heartbeat(self.session_id, self.epoch)
        if self.mc:
            self.mc.heartbeat(self.session_id, self.epoch)
            self.repository.reconcile_mc(self.mc.state().get("executions", []))
        self.dcc_ready = True
        self.last_error = None
        return result

    def snapshot(self):
        return {"session_id": self.session_id, "epoch": self.epoch,
                "started": self.started, "dcc_ready": self.dcc_ready, "mc_ready": self.mc_ready,
                "last_error": self.last_error,
                "emergency_latched": self.emergency_latched}

    def hmi_snapshot(self):
        self._require_started()
        dcc = self.dcc.state()
        mc = self.mc.state() if self.mc else {"broker": "offline", "nodes": [], "servo_gate": None, "machine_gate": None}
        return {
            "generation": f"{self.session_id}:{self.epoch}",
            "emergency_latched": self.emergency_latched,
            "device": dcc["device"],
            "mc": mc,
        }

    def hmi_locomotives(self):
        return self.asset.locomotives()

    def hmi_devices(self):
        return self.dcc.devices()

    def hmi_stationary(self):
        return self.asset.stationary()

    def hmi_command(self, operation, payload, command_id):
        if operation == "device.connect":
            return self.device_connect(payload.get("selection_id"), command_id)
        if operation == "device.disconnect":
            return self.device_disconnect(command_id)
        if operation == "main_power":
            return self.main_power(payload.get("on"), command_id)
        if operation == "throttle":
            return self.throttle(payload.get("asset_id"), payload.get("speed"), payload.get("direction"), command_id)
        if operation == "function":
            return self.function(payload.get("asset_id"), payload.get("number"), payload.get("active"), command_id)
        if operation == "stop":
            return self.stop(payload.get("asset_id"), command_id)
        if operation == "emergency_stop":
            return self.emergency_stop(command_id)
        if operation == "resume":
            return self.resume()
        if operation in {"turnout.set", "signal.set", "machine.execute"}:
            return self.stationary(operation, payload.get("asset_id"), payload.get("value"), command_id)
        raise ValueError(f"Unsupported HMI operation: {operation}")

    def stationary(self, operation, asset_id, value, command_id=None):
        self._require_started()
        if not self.mc:
            raise CoreConflict("MC service is unavailable")
        asset = self.asset.get(asset_id)
        expected_family = {"turnout.set": "turnout", "signal.set": "signal", "machine.execute": "machine"}[operation]
        life, control = asset.get("lifecycle") or {}, asset.get("control") or {}
        if asset.get("family") != expected_family:
            raise CoreConflict(f"Asset is not a {expected_family}")
        if life.get("possession") != "received" or life.get("status") != "active":
            raise CoreConflict("Stationary asset must be received and active")
        node_id = control.get("node_id")
        if not isinstance(node_id, str) or not node_id:
            raise CoreConflict("Stationary asset requires a control node")
        if operation == "turnout.set" and value not in {"straight", "diverging"}:
            raise ValueError("turnout state must be straight or diverging")
        if operation == "signal.set":
            allowed = {"stop", "go"} if asset.get("type", "").endswith("2a") else {"stop", "slow", "go"}
            if value not in allowed: raise ValueError("unsupported signal aspect")
        if operation == "machine.execute" and value not in control.get("actions", ["operate"]):
            raise ValueError("unsupported machine action")
        journal = {"value": value}
        replay = self._existing(command_id, operation, asset_id, journal)
        if replay: return replay
        lease = self.asset.acquire_lease(asset_id, asset["revision"], self.session_id, self.epoch, operation)
        resources = [] if operation == "signal.set" else ["servo"] if operation == "turnout.set" else list(control.get("resources") or ["machine"])
        cid = command_id or str(uuid.uuid4())
        execution_id = str(uuid.uuid4())
        self.repository.begin(cid, operation, journal, asset_id)
        from datetime import UTC, datetime, timedelta
        envelope = {"command_id": cid, "execution_id": execution_id,
                    "core_session_id": self.session_id, "core_epoch": self.epoch,
                    "asset_id": asset_id, "asset_revision": asset["revision"],
                    "configuration_revision": control.get("configuration_revision", asset["revision"]),
                    "lease_id": lease["lease_id"], "fencing_token": lease["fencing_token"],
                    "node_id": node_id, "operation": operation, "value": value,
                    "resources": resources,
                    "expires_at": (datetime.now(UTC) + timedelta(seconds=10)).isoformat()}
        try:
            result = self.mc.submit(envelope)
            self.repository.finish(cid, "accepted", result.get("state"), result)
            return {"command_id": cid, "execution_id": execution_id, **result}
        except Exception:
            self.repository.finish(cid, "uncertain")
            raise

    def device_connect(self, selection_id, command_id=None):
        self._require_started()
        if not isinstance(selection_id, str) or not selection_id:
            raise ValueError("selection_id required")
        return self._dispatch(command_id, "device_connect", None,
                              {"selection_id": selection_id}, "/v1/device/connect",
                              {"selection_id": selection_id})

    def device_disconnect(self, command_id=None):
        self._require_started()
        return self._dispatch(command_id, "device_disconnect", None, {},
                              "/v1/device/disconnect", {})

    def main_power(self, on, command_id=None):
        self._require_started()
        if type(on) is not bool:
            raise ValueError("on must be boolean")
        if on and self.emergency_latched:
            raise CoreConflict("Emergency stop is active")
        replay = self._existing(command_id, "main_power", None, {"on": on})
        if replay:
            return replay
        return self._dispatch(command_id, "main_power", None, {"on": on},
                              "/v1/main/power", {"on": on})

    def throttle(self, asset_id, speed, direction, command_id=None):
        self._require_started()
        if self.emergency_latched:
            raise CoreConflict("Emergency stop is active")
        payload = {"speed": speed, "direction": direction}
        replay = self._existing(command_id, "throttle", asset_id, payload)
        if replay:
            return replay
        asset, lease, address = self._operating_locomotive(asset_id, "throttle")
        return self._dispatch(command_id, "throttle", asset_id, payload,
                              f"/v1/locomotives/{address}/throttle", payload, asset, lease)

    def function(self, asset_id, number, active, command_id=None):
        self._require_started()
        if self.emergency_latched:
            raise CoreConflict("Emergency stop is active")
        if type(number) is not int or not 0 <= number <= 68 or type(active) is not bool:
            raise ValueError("function number must be 0..68 and active must be boolean")
        journal_payload = {"number": number, "active": active}
        replay = self._existing(command_id, "function", asset_id, journal_payload)
        if replay:
            return replay
        asset, lease, address = self._operating_locomotive(asset_id, "function")
        payload = {"active": active}
        return self._dispatch(command_id, "function", asset_id, journal_payload,
                              f"/v1/locomotives/{address}/functions/{number}", payload, asset, lease)

    def stop(self, asset_id, command_id=None):
        self._require_started()
        replay = self._existing(command_id, "stop", asset_id, {})
        if replay:
            return replay
        reservation = self.repository.reservation(asset_id)
        if not reservation or type(reservation.get("address")) is not int:
            asset, lease, address = self._operating_locomotive(asset_id, "stop")
        else:
            asset = self.asset.get(asset_id)
            lease = {"lease_id": reservation["lease_id"], "fencing_token": reservation["fencing_token"]}
            address = reservation["address"]
        return self._dispatch(command_id, "stop", asset_id, {},
                              f"/v1/locomotives/{address}/stop", {}, asset, lease)

    def emergency_stop(self, command_id=None):
        with self._lock:
            self.emergency_latched = True
        cid = command_id or str(uuid.uuid4())
        existing = self.repository.begin(cid, "emergency_stop", {})
        if existing:
            return {"command_id": cid, **(self._stored_result(existing)), "replayed": True}
        try:
            result = self.dcc.emergency_stop()
            self.repository.finish(cid, "completed", result.get("outcome"), result)
            return {"command_id": cid, **result, "emergency_latched": True}
        except Exception:
            self.repository.finish(cid, "uncertain")
            raise

    def resume(self):
        self._require_started()
        with self._lock:
            self.emergency_latched = False
        return self.snapshot()

    def close(self):
        self._shutdown.set()
        if self._heartbeat_thread and self._heartbeat_thread is not threading.current_thread():
            self._heartbeat_thread.join(timeout=1)

    def _heartbeat_loop(self):
        while not self._shutdown.wait(self._heartbeat_interval):
            try:
                self.heartbeat()
            except Exception as error:
                self.dcc_ready = False
                self.mc_ready = False
                self.last_error = str(error)

    def _operating_locomotive(self, asset_id, purpose):
        asset = self.asset.get(asset_id)
        life, control = asset.get("lifecycle") or {}, asset.get("control") or {}
        address = control.get("address")
        if asset.get("family") != "loco":
            raise CoreConflict("Asset is not a locomotive")
        if life.get("possession") != "received" or life.get("status") != "active":
            raise CoreConflict("Locomotive must be received and active")
        if control.get("dcc") is not True or type(address) is not int or not 1 <= address <= 10293:
            raise CoreConflict("Locomotive requires a valid DCC configuration")
        lease = self.asset.acquire_lease(
            asset_id, asset["revision"], self.session_id, self.epoch, purpose
        )
        self.repository.reserve(asset_id, lease, asset["revision"], address)
        return asset, lease, address

    def _dispatch(self, command_id, operation, asset_id, journal_payload, path,
                  device_payload, asset=None, lease=None):
        cid = command_id or str(uuid.uuid4())
        existing = self.repository.begin(cid, operation, journal_payload, asset_id)
        if existing:
            return {"command_id": cid, **self._stored_result(existing), "replayed": True}
        envelope = {"command_id": cid, "core_session_id": self.session_id, "core_epoch": self.epoch, **device_payload}
        if asset is not None:
            envelope.update(asset_id=asset_id, asset_revision=asset["revision"],
                            lease_id=lease["lease_id"], fencing_token=lease["fencing_token"])
        try:
            result = self.dcc.command(path, envelope)
            self.repository.finish(cid, "completed", result.get("outcome"), result)
            return {"command_id": cid, **result}
        except Exception:
            self.repository.finish(cid, "uncertain")
            raise

    def _require_started(self):
        if not self.started:
            raise CoreConflict("Core has not established a DCC session")

    def _existing(self, command_id, operation, asset_id, payload):
        row = self.repository.existing(command_id, operation, payload, asset_id)
        if not row:
            return None
        if row["state"] != "completed" and row.get("result"):
            import json
            return {"command_id": command_id, **json.loads(row["result"]), "replayed": True}
        return {"command_id": command_id, **self._stored_result(row), "replayed": True}

    @staticmethod
    def _stored_result(row):
        import json
        if row["state"] != "completed" or not row.get("result"):
            raise CoreConflict("Command is still pending or requires reconciliation")
        return json.loads(row["result"])
