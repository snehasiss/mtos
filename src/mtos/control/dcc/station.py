"""Single-owner, bounded DCC-EX command-station adapter."""

from __future__ import annotations

import threading
import time
import uuid
from collections import deque
from datetime import UTC, datetime

from ..models import (
    CommandResult,
    ConnectionState,
    DeviceState,
    LocoState,
    PowerState,
)
from .protocol import (
    Framer,
    encode_emergency_stop,
    encode_cv_read,
    encode_cv_write,
    encode_function,
    encode_main_power,
    encode_throttle,
    parse_frame,
)
from .transport import PySerialTransport


def utcnow():
    return datetime.now(UTC).isoformat()


class DccExStation:
    """Own one serial connection; calls are serialized and bounded."""

    def __init__(self, transport=None, *, response_timeout=0.8, handshake_timeout=5.0):
        self.transport = transport or PySerialTransport()
        self.response_timeout = response_timeout
        self.handshake_timeout = handshake_timeout
        self.state = DeviceState()
        self._state_lock = threading.RLock()
        self._changed = threading.Condition(self._state_lock)
        self._operation_lock = threading.RLock()
        self._write_lock = threading.Lock()
        self._running = threading.Event()
        self._reader = None
        self._events = deque(maxlen=256)
        self._event_sequence = 0
        self._program_callback = 0
        self._framer = Framer()

    def snapshot(self):
        with self._state_lock:
            return self.state.to_dict()

    def connect(self, port, *, baud_rate=115200, read_timeout=0.05, write_timeout=0.5):
        with self._operation_lock:
            if self.state.connection == ConnectionState.READY:
                return self.snapshot()
            with self._state_lock:
                self.state = DeviceState(connection=ConnectionState.CONNECTING, port=port)
            try:
                self.transport.open(port, baud_rate, read_timeout, write_timeout)
                self._framer.reset()
                self._running.set()
                self._reader = threading.Thread(
                    target=self._read_loop, name="mtos-csb1-reader", daemon=True
                )
                self._reader.start()
                self._write("<s>")
                self._write("<=>")
                deadline = time.monotonic() + self.handshake_timeout
                with self._changed:
                    while time.monotonic() < deadline and (
                        not self.state.identity or not self.state.main.mode
                    ):
                        self._changed.wait(max(0, deadline - time.monotonic()))
                if not self.state.identity:
                    raise TimeoutError("Device did not return a DCC-EX identity")
                with self._state_lock:
                    self.state.connection = ConnectionState.READY
                    self.state.session_id = str(uuid.uuid4())
                    self.state.stale = False
                return self.snapshot()
            except Exception as exc:
                self._running.clear()
                self.transport.close()
                if self._reader and self._reader is not threading.current_thread():
                    self._reader.join(timeout=1)
                with self._state_lock:
                    self.state.connection = ConnectionState.ERROR
                    self.state.error = str(exc)
                    self.state.stale = True
                raise

    def disconnect(self):
        with self._operation_lock:
            self._running.clear()
            self.transport.close()
            if self._reader and self._reader is not threading.current_thread():
                self._reader.join(timeout=1)
            self._reader = None
            with self._state_lock:
                self.state.connection = ConnectionState.DISCONNECTED
                self.state.session_id = None
                self.state.stale = True
                self.state.main.power = PowerState.UNKNOWN
                self.state.locomotives.clear()
            return self.snapshot()

    def set_main_power(self, on):
        with self._operation_lock:
            self._require_ready()
            if on and not (self.state.main.mode or "").startswith("MAIN"):
                raise RuntimeError("A MAIN output was not verified")
            frame = encode_main_power(on)
            marker = self._event_sequence
            self._write(frame)
            event = self._wait_for(
                lambda e: e.kind == "power"
                and e.data["scope"] in ("MAIN", "ALL")
                and e.data["state"] == ("on" if on else "off"), marker
            )
            return CommandResult(
                "confirmed" if event else "uncertain",
                "main_power",
                requested={"on": on},
                reported={"power": self.state.main.power} if event else None,
                detail=None if event else "MAIN power report was not received",
            )

    def throttle(self, address, speed, direction):
        return self._operating(
            encode_throttle(address, speed, direction), "throttle", address,
            {"speed": speed, "direction": direction},
            lambda e: e.kind == "locomotive" and e.data["address"] == address
            and e.data["speed"] == speed and e.data["direction"] == direction,
        )

    def function(self, address, number, active):
        result = self._operating(
            encode_function(address, number, active), "function", address,
            {"number": number, "active": active}, None,
        )
        with self._state_lock:
            loco = self.state.locomotives.setdefault(str(address), LocoState(address))
            loco.desired_functions[str(number)] = active
        return result

    def read_cv(self, cv):
        callback = self._next_program_callback()
        event = self._program_request(
            encode_cv_read(cv, callback),
            lambda candidate: candidate.kind == "cv"
            and candidate.data.get("cv") == cv
            and candidate.data.get("callback") == callback,
        )
        value = event.data["value"]
        if value < 0:
            raise RuntimeError(f"Decoder did not acknowledge CV {cv}")
        return value

    def write_cv(self, cv, value):
        event = self._program_request(
            encode_cv_write(cv, value),
            lambda candidate: candidate.kind == "cv"
            and candidate.data.get("cv") == cv,
        )
        if event.data.get("value") != value:
            raise RuntimeError(f"Decoder did not confirm writing CV {cv}")
        return value

    def program_address(self, old_address, new_address):
        with self._operation_lock:
            _ = old_address  # Service-mode programming is address-independent.
            if type(new_address) is not int or not 1 <= new_address <= 10239:
                raise ValueError("new DCC address must be from 1 through 10239")
            cv29 = self.read_cv(29)
            if new_address <= 127:
                expected = {1: new_address, 29: cv29 & ~0x20}
                self.write_cv(1, expected[1])
                self.write_cv(29, expected[29])
            else:
                expected = {
                    17: 192 + (new_address // 256),
                    18: new_address % 256,
                    29: cv29 | 0x20,
                }
                self.write_cv(17, expected[17])
                self.write_cv(18, expected[18])
                self.write_cv(29, expected[29])
            verified = {cv: self.read_cv(cv) for cv in expected}
            if verified != expected:
                raise RuntimeError("Decoder address readback did not match the requested address")
            return CommandResult(
                "confirmed", "program_address",
                requested={"old_address": old_address, "new_address": new_address},
                reported={"address": new_address, "cvs": verified},
            )

    def stop(self, address, direction):
        return self.throttle(address, 0, direction)

    def emergency_stop(self):
        with self._write_lock:
            self._require_ready()
            self.transport.write(encode_emergency_stop().encode("ascii"))
            with self._state_lock:
                for loco in self.state.locomotives.values():
                    loco.speed = 0
            return CommandResult("accepted_unverified", "emergency_stop")

    def _operating(self, frame, operation, address, requested, matcher):
        with self._operation_lock:
            self._require_ready()
            marker = self._event_sequence
            self._write(frame)
            event = self._wait_for(matcher, marker) if matcher else None
            loco = self.state.locomotives.get(str(address))
            return CommandResult(
                "confirmed" if event else "accepted_unverified",
                operation,
                requested=requested,
                reported=(
                    {"speed": loco.speed, "direction": loco.direction}
                    if event and loco else None
                ),
            )

    def _require_ready(self):
        if self.state.connection != ConnectionState.READY or not self.transport.is_open:
            raise RuntimeError("EX-CSB1 is not ready")

    def _write(self, frame):
        with self._write_lock:
            self.transport.write(frame.encode("ascii"))

    def _program_request(self, frame, matcher):
        with self._operation_lock:
            self._require_ready()
            if self.state.main.power != PowerState.OFF:
                raise RuntimeError("MAIN track power must be confirmed off before service-mode programming")
            if self.state.prog.mode != "PROG":
                raise RuntimeError("A PROG output was not verified")
            marker = self._event_sequence
            self._write(frame)
            event = self._wait_for(matcher, marker, timeout=15.0)
            if event is None:
                raise TimeoutError("EX-CSB1 did not confirm the programming command")
            return event

    def _next_program_callback(self):
        with self._state_lock:
            self._program_callback = self._program_callback % 32767 + 1
            return self._program_callback

    def _wait_for(self, matcher, marker, timeout=None):
        deadline = time.monotonic() + (self.response_timeout if timeout is None else timeout)
        with self._changed:
            while time.monotonic() < deadline:
                for sequence, event in self._events:
                    if sequence > marker and matcher(event):
                        return event
                self._changed.wait(max(0, deadline - time.monotonic()))
        return None

    def _read_loop(self):
        try:
            while self._running.is_set() and self.transport.is_open:
                if not self._read_once():
                    time.sleep(0.001)
        except Exception as exc:
            if self._running.is_set():
                with self._changed:
                    self.state.connection = ConnectionState.ERROR
                    self.state.error = str(exc)
                    self.state.stale = True
                    self._changed.notify_all()
            self._running.clear()

    def _read_once(self):
        count = 0
        for frame in self._framer.feed(self.transport.read()):
            count += 1
            event = parse_frame(frame)
            with self._changed:
                self.state.last_seen = utcnow()
                self.state.stale = False
                if event.kind == "identity":
                    self.state.identity = event.data["identity"]
                elif event.kind == "power":
                    if event.data["scope"] in ("MAIN", "ALL"):
                        self.state.main.power = PowerState(event.data["state"])
                elif event.kind == "track" and event.data["mode"].startswith("MAIN"):
                    self.state.main.letter = event.data["letter"]
                    self.state.main.mode = event.data["mode"]
                elif event.kind == "track" and event.data["mode"] == "PROG":
                    self.state.prog.letter = event.data["letter"]
                    self.state.prog.mode = event.data["mode"]
                elif event.kind == "locomotive":
                    data = event.data
                    key = str(data["address"])
                    previous = self.state.locomotives.get(key)
                    desired = dict(previous.desired_functions) if previous else {}
                    self.state.locomotives[key] = LocoState(
                        **data, desired_functions=desired
                    )
                self._event_sequence += 1
                self._events.append((self._event_sequence, event))
                self._changed.notify_all()
        return count
