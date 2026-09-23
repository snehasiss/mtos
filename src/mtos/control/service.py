"""Application orchestration for CSB1 MAIN locomotive control."""

from __future__ import annotations

import threading
import uuid

from ..roster import Conflict
from .dcc.station import DccExStation
from .repository import ControlRepository


class ControlService:
    def __init__(self, root=None, station=None):
        self.repository = ControlRepository(root)
        self.station = station or DccExStation()
        self.generation = str(uuid.uuid4())
        self.emergency_latched = False
        self._lock = threading.RLock()

    def snapshot(self):
        return {
            "generation": self.generation,
            "emergency_latched": self.emergency_latched,
            "device": self.station.snapshot(),
        }

    def devices(self):
        try:
            from serial.tools import list_ports
        except ImportError:
            return []
        ports = [
            {
                "selection_id": p.device,
                "port": p.device,
                "description": p.description,
                "manufacturer": p.manufacturer,
                "vid": p.vid,
                "pid": p.pid,
                "serial_number": p.serial_number,
            }
            for p in list_ports.comports()
        ]
        tokens = ("usbmodem", "usbserial", "ttyacm", "ttyusb")
        return [
            item
            for item in ports
            if item["vid"] is not None
            or any(token in item["port"].lower() for token in tokens)
        ]

    def connect(self, selection=None):
        candidates = self.devices()
        if selection:
            matches = [c for c in candidates if c["selection_id"] == selection]
            if not matches:
                raise ValueError("Selected serial device is unavailable")
            port = matches[0]["port"]
        elif len(candidates) == 1:
            port = candidates[0]["port"]
        else:
            raise Conflict("Select one serial device" if candidates else "No serial device found")
        result = self.station.connect(port)
        with self._lock:
            self.generation = str(uuid.uuid4())
            self.emergency_latched = False
        return result

    def disconnect(self):
        with self._lock:
            self.generation = str(uuid.uuid4())
            self.emergency_latched = False
        return self.station.disconnect()

    def main_power(self, on, generation):
        self._current(generation)
        result = self.station.set_main_power(on)
        self.repository.command("main_power", None, {"on": on}, outcome=result.outcome)
        return result.to_dict()

    def throttle(self, asset_id, speed, direction, generation):
        self._movement_allowed(generation)
        asset = self.repository.operating_asset(asset_id)
        session_id = self.station.state.session_id
        address = self.repository.reserve(asset, session_id)
        result = self.station.throttle(address, speed, direction)
        result = result.__class__(**{**result.__dict__, "asset_id": asset_id})
        self.repository.command("throttle", asset_id, result.requested, outcome=result.outcome)
        return result.to_dict()

    def function(self, asset_id, number, active, generation):
        self._movement_allowed(generation)
        asset = self.repository.operating_asset(asset_id)
        address = self.repository.reserve(asset, self.station.state.session_id)
        result = self.station.function(address, number, active)
        result = result.__class__(**{**result.__dict__, "asset_id": asset_id})
        self.repository.command("function", asset_id, result.requested, outcome=result.outcome)
        return result.to_dict()

    def stop(self, asset_id):
        with self.repository.roster.connect() as db:
            row = db.execute(
                "SELECT address FROM control_reservation WHERE asset_id=?", (asset_id,)
            ).fetchone()
        if row:
            address = row["address"]
        else:
            asset = self.repository.roster.get(asset_id)
            address = ((asset.get("control") or {}).get("decoder") or {}).get("address")
        if type(address) is not int:
            raise Conflict("No DCC address is available for stop")
        with self._lock:
            self.generation = str(uuid.uuid4())
        direction = self.station.state.locomotives.get(str(address))
        result = self.station.stop(address, direction.direction if direction else "forward")
        self.repository.command("stop", asset_id, {}, outcome=result.outcome)
        return {**result.to_dict(), "generation": self.generation}

    def emergency_stop(self):
        with self._lock:
            self.generation = str(uuid.uuid4())
            self.emergency_latched = True
        result = self.station.emergency_stop()
        self.repository.command("emergency_stop", None, {}, outcome=result.outcome)
        return {**result.to_dict(), "generation": self.generation}

    def resume(self, generation):
        self._current(generation)
        with self._lock:
            self.generation = str(uuid.uuid4())
            self.emergency_latched = False
        return self.snapshot()

    def release(self, asset_id):
        reservation = None
        with self.repository.roster.connect() as db:
            reservation = db.execute(
                "SELECT address FROM control_reservation WHERE asset_id=?", (asset_id,)
            ).fetchone()
        if reservation:
            loco = self.station.state.locomotives.get(str(reservation["address"]))
            if self.station.state.main.power.value != "off" and (not loco or loco.speed != 0):
                raise Conflict("Stop the locomotive or turn MAIN power off before release")
            self.repository.release(asset_id, self.station.state.session_id)
        return {"released": asset_id}

    def _current(self, generation):
        if generation != self.generation:
            raise Conflict("Control state changed; refresh before retrying")

    def _movement_allowed(self, generation):
        self._current(generation)
        if self.emergency_latched:
            raise Conflict("Emergency stop is active")
        if self.station.state.main.power.value != "on":
            raise Conflict("MAIN power is not confirmed on")
