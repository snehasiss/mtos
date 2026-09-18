"""Fenced, address-level ownership of one DCC command station."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass

from ..control.dcc.station import DccExStation


class DccBusy(RuntimeError):
    pass


class StaleCoreSession(RuntimeError):
    pass


@dataclass
class CoreSession:
    session_id: str
    epoch: int
    last_heartbeat: float
    stale: bool = False


class DccService:
    """Own the serial adapter; Core owns assets, policy and command identity."""

    def __init__(
        self,
        station=None,
        *,
        heartbeat_timeout=6.0,
        clock=time.monotonic,
        queue_capacity=64,
        watchdog_interval=0.25,
    ):
        self.station = station or DccExStation()
        self.heartbeat_timeout = heartbeat_timeout
        self.clock = clock
        self.core: CoreSession | None = None
        self._lock = threading.RLock()
        self._normal_slots = threading.BoundedSemaphore(queue_capacity)
        self._asset_fences: dict[str, int] = {}
        self._watchdog_stop_sent = False
        self._watchdog_interval = watchdog_interval
        self._shutdown = threading.Event()
        self._watchdog = None
        if watchdog_interval is not None:
            self._watchdog = threading.Thread(
                target=self._watchdog_loop, name="mtos-dcc-watchdog", daemon=True
            )
            self._watchdog.start()

    def snapshot(self):
        with self._lock:
            core = None if self.core is None else {
                "session_id": self.core.session_id,
                "epoch": self.core.epoch,
                "stale": self.core.stale,
            }
        return {"core": core, "device": self.station.snapshot()}

    def devices(self):
        try:
            from serial.tools import list_ports
        except ImportError:
            return []
        tokens = ("usbmodem", "usbserial", "ttyacm", "ttyusb")
        items = []
        for port in list_ports.comports():
            if port.vid is None and not any(token in port.device.lower() for token in tokens):
                continue
            items.append({
                "selection_id": port.device, "port": port.device,
                "description": port.description, "manufacturer": port.manufacturer,
                "vid": port.vid, "pid": port.pid, "serial_number": port.serial_number,
            })
        return items

    def establish_core_session(self, session_id: str, epoch: int):
        if not session_id or type(epoch) is not int or epoch < 1:
            raise ValueError("valid session_id and positive integer epoch required")
        with self._lock:
            if self.core and epoch <= self.core.epoch and session_id != self.core.session_id:
                raise StaleCoreSession("Core epoch must increase for a new session")
            self.core = CoreSession(session_id, epoch, self.clock())
            self._watchdog_stop_sent = False
        return self.snapshot()["core"]

    def heartbeat(self, session_id: str, epoch: int):
        with self._lock:
            self._require_session(session_id, epoch, allow_stale=True)
            self.core.last_heartbeat = self.clock()
            self.core.stale = False
            self._watchdog_stop_sent = False
            return self.snapshot()["core"]

    def check_watchdog(self, now=None):
        with self._lock:
            if not self.core or self.core.stale:
                return False
            if (self.clock() if now is None else now) - self.core.last_heartbeat <= self.heartbeat_timeout:
                return False
            self.core.stale = True
        if not self._watchdog_stop_sent:
            try:
                self.station.emergency_stop()
            except RuntimeError:
                pass
            self._watchdog_stop_sent = True
        return True

    def validate(self, envelope: dict, *, asset_required=True):
        self.check_watchdog()
        session_id = envelope.get("core_session_id")
        epoch = envelope.get("core_epoch")
        with self._lock:
            self._require_session(session_id, epoch)
            if asset_required:
                asset_id = envelope.get("asset_id")
                fence = envelope.get("fencing_token")
                if not isinstance(asset_id, str) or type(fence) is not int or fence < 1:
                    raise ValueError("asset_id and positive fencing_token required")
                previous = self._asset_fences.get(asset_id, 0)
                if fence < previous:
                    raise StaleCoreSession("stale asset fencing token")
                self._asset_fences[asset_id] = fence

    def execute(self, envelope, operation, action, *, asset_required=True):
        self.validate(envelope, asset_required=asset_required)
        if not self._normal_slots.acquire(blocking=False):
            raise DccBusy("DCC command queue is full")
        try:
            result = action()
            return result.to_dict() if hasattr(result, "to_dict") else result
        finally:
            self._normal_slots.release()

    def emergency_stop(self):
        return self.station.emergency_stop().to_dict()

    def close(self):
        self._shutdown.set()
        if self._watchdog and self._watchdog is not threading.current_thread():
            self._watchdog.join(timeout=1)
        try:
            self.station.disconnect()
        except Exception:
            pass

    def _watchdog_loop(self):
        while not self._shutdown.wait(self._watchdog_interval):
            self.check_watchdog()

    def _require_session(self, session_id, epoch, *, allow_stale=False):
        if not self.core or session_id != self.core.session_id or epoch != self.core.epoch:
            raise StaleCoreSession("unknown or stale Core session")
        if self.core.stale and not allow_stale:
            raise StaleCoreSession("Core heartbeat is stale")
