"""Typed values shared by the control service and device adapter."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import StrEnum


class ConnectionState(StrEnum):
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    READY = "ready"
    ERROR = "error"


class PowerState(StrEnum):
    UNKNOWN = "unknown"
    OFF = "off"
    ON = "on"
    FAULT = "fault"


@dataclass
class OutputState:
    letter: str | None = None
    mode: str | None = None
    power: PowerState = PowerState.UNKNOWN


@dataclass
class LocoState:
    address: int
    speed: int = 0
    direction: str = "forward"
    functions: dict[str, bool] = field(default_factory=dict)
    desired_functions: dict[str, bool] = field(default_factory=dict)


@dataclass
class DeviceState:
    connection: ConnectionState = ConnectionState.DISCONNECTED
    session_id: str | None = None
    port: str | None = None
    identity: str | None = None
    firmware: str | None = None
    last_seen: str | None = None
    stale: bool = True
    main: OutputState = field(default_factory=OutputState)
    prog: OutputState = field(default_factory=OutputState)
    error: str | None = None
    locomotives: dict[str, LocoState] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class ProtocolEvent:
    kind: str
    data: dict
    raw: str


@dataclass(frozen=True)
class CommandResult:
    outcome: str
    operation: str
    asset_id: str | None = None
    requested: dict = field(default_factory=dict)
    reported: dict | None = None
    detail: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)
