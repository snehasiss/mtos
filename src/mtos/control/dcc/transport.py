"""Serial transport boundary. Importing this module never opens hardware."""

from __future__ import annotations

from typing import Protocol


class SerialTransport(Protocol):
    @property
    def is_open(self) -> bool: ...
    def open(self, port: str, baud_rate: int, timeout: float, write_timeout: float): ...
    def read(self, size: int = 1) -> bytes: ...
    def write(self, data: bytes): ...
    def close(self): ...


class PySerialTransport:
    def __init__(self):
        self.serial = None

    @property
    def is_open(self):
        return bool(self.serial and self.serial.is_open)

    def open(self, port, baud_rate, timeout, write_timeout):
        import serial

        self.serial = serial.Serial(
            port=port, baudrate=baud_rate, timeout=timeout, write_timeout=write_timeout
        )

    def read(self, size=1):
        return self.serial.read(max(size, self.serial.in_waiting or 1))

    def write(self, data):
        count = self.serial.write(data)
        self.serial.flush()
        if count != len(data):
            raise OSError("partial serial write")

    def close(self):
        if self.serial and self.serial.is_open:
            self.serial.close()
        self.serial = None
