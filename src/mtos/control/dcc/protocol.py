"""Validated DCC-EX encoders, framing and response parsing."""

from __future__ import annotations

import re

from ..models import ProtocolEvent


class Framer:
    def __init__(self, maximum=4096):
        self.buffer = ""
        self.maximum = maximum

    def reset(self):
        self.buffer = ""

    def feed(self, chunk: bytes | str) -> list[str]:
        self.buffer += (
            chunk.decode("ascii", errors="replace") if isinstance(chunk, bytes) else chunk
        )
        frames = []
        while True:
            start = self.buffer.find("<")
            if start < 0:
                self.buffer = self.buffer[-self.maximum :]
                return frames
            self.buffer = self.buffer[start:]
            end = self.buffer.find(">", 1)
            if end < 0:
                if len(self.buffer) > self.maximum:
                    self.buffer = ""
                return frames
            frames.append(self.buffer[: end + 1])
            self.buffer = self.buffer[end + 1 :]


def _address(address):
    if type(address) is not int or not 1 <= address <= 10239:
        raise ValueError("DCC address must be between 1 and 10239")


def encode_main_power(on: bool) -> str:
    if type(on) is not bool:
        raise ValueError("power state must be boolean")
    return f"<{'1' if on else '0'} MAIN>"


def encode_throttle(address: int, speed: int, direction: str) -> str:
    _address(address)
    if type(speed) is not int or not 0 <= speed <= 126:
        raise ValueError("speed must be an integer from 0 through 126")
    if direction not in ("forward", "reverse"):
        raise ValueError("direction must be forward or reverse")
    return f"<t {address} {speed} {1 if direction == 'forward' else 0}>"


def encode_function(address: int, number: int, active: bool) -> str:
    _address(address)
    if type(number) is not int or not 0 <= number <= 68:
        raise ValueError("function must be from 0 through 68")
    if type(active) is not bool:
        raise ValueError("function state must be boolean")
    return f"<F {address} {number} {1 if active else 0}>"


def encode_cv_read(cv: int, callback: int, callback_sub: int = 0) -> str:
    if type(cv) is not int or not 1 <= cv <= 1024:
        raise ValueError("CV must be an integer from 1 through 1024")
    if type(callback) is not int or not 0 <= callback <= 32767:
        raise ValueError("callback must be an integer from 0 through 32767")
    if type(callback_sub) is not int or not 0 <= callback_sub <= 32767:
        raise ValueError("callback_sub must be an integer from 0 through 32767")
    return f"<R {cv} {callback} {callback_sub}>"


def encode_cv_write(cv: int, value: int) -> str:
    if type(cv) is not int or not 1 <= cv <= 1024:
        raise ValueError("CV must be an integer from 1 through 1024")
    if type(value) is not int or not 0 <= value <= 255:
        raise ValueError("CV value must be an integer from 0 through 255")
    return f"<W {cv} {value}>"


def encode_emergency_stop() -> str:
    return "<!>"


def parse_frame(frame: str) -> ProtocolEvent:
    body = frame[1:-1].strip() if frame.startswith("<") and frame.endswith(">") else frame
    if body.startswith("iDCC-EX"):
        return ProtocolEvent("identity", {"identity": body[1:]}, frame)
    match = re.fullmatch(r"p([01])(?:\s+(\w+))?", body, re.I)
    if match:
        return ProtocolEvent(
            "power", {"state": "on" if match[1] == "1" else "off", "scope": (match[2] or "all").upper()}, frame
        )
    match = re.fullmatch(r"=\s*([A-H])\s+([A-Z_]+)(?:\s+\d+)?", body, re.I)
    if match:
        return ProtocolEvent("track", {"letter": match[1].upper(), "mode": match[2].upper()}, frame)
    if body.startswith("r"):
        parts = body[1:].strip().split()
        try:
            if len(parts) == 2 and "|" in parts[0]:
                callback, callback_sub, cv = parts[0].split("|")
                return ProtocolEvent(
                    "cv",
                    {"cv": int(cv), "value": int(parts[1]),
                     "callback": int(callback), "callback_sub": int(callback_sub)},
                    frame,
                )
            if len(parts) == 2:
                return ProtocolEvent("cv", {"cv": int(parts[0]), "value": int(parts[1])}, frame)
        except ValueError:
            pass
    parts = body.split()
    if len(parts) >= 5 and parts[0] == "l":
        try:
            address, speed_byte, function_map = int(parts[1]), int(parts[3]), int(parts[4])
        except ValueError:
            pass
        else:
            direction = "forward" if speed_byte >= 128 else "reverse"
            if speed_byte in (0, 1, 128, 129):
                speed = 0
            else:
                speed = speed_byte - 129 if direction == "forward" else speed_byte - 1
            return ProtocolEvent(
                "locomotive",
                {"address": address, "speed": max(0, speed), "direction": direction,
                 "functions": {str(n): bool(function_map & (1 << n)) for n in range(16)}},
                frame,
            )
    return ProtocolEvent("unknown", {"body": body}, frame)
