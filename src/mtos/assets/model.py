"""Normalized values and aggregates for the MTOS asset roster."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timezone
from enum import StrEnum
import re
from typing import Any

_ASSET_ID = re.compile(r"^[A-Z][0-9]{3}$")
_CONSIST_ID = re.compile(r"^K[0-9]{3}$")
_SNAKE_CASE = re.compile(r"^[a-z][a-z0-9]*(?:_[a-z0-9]+)*$")
_BLOCK = re.compile(r"^block[0-9]+$")


class AssetFamily(StrEnum):
    LOCO = "loco"
    MOW = "mow"
    PASSENGER = "passenger"
    FREIGHT = "freight"
    NODE = "node"
    TURNOUT = "turnout"
    SIGNAL = "signal"
    MACHINE = "machine"
    BUILDING = "building"


PREFIXES: dict[AssetFamily, str] = {
    AssetFamily.LOCO: "L", AssetFamily.MOW: "M", AssetFamily.PASSENGER: "C",
    AssetFamily.FREIGHT: "C", AssetFamily.NODE: "N", AssetFamily.TURNOUT: "T",
    AssetFamily.SIGNAL: "G", AssetFamily.MACHINE: "E", AssetFamily.BUILDING: "B",
}

TYPES: dict[AssetFamily, frozenset[str]] = {
    AssetFamily.LOCO: frozenset({"diesel", "turbine", "steam", "booster"}),
    AssetFamily.MOW: frozenset({"tamper", "mpv", "track_cleaner", "crane", "snowplow"}),
    AssetFamily.PASSENGER: frozenset(
        {"coach", "balcony", "heater_car", "power_car", "luggage", "brakevan"}
    ),
    AssetFamily.FREIGHT: frozenset(
        {"wagon", "tanker", "gondola", "intermodal", "flat_car", "reefer"}
    ),
    AssetFamily.NODE: frozenset({"control_node"}),
    AssetFamily.TURNOUT: frozenset({"left", "right", "wye", "crossing", "double_slip"}),
    AssetFamily.SIGNAL: frozenset({"ground_2a", "mainline_3a", "branchline_2a"}),
    AssetFamily.MACHINE: frozenset({"water_tank", "turntable"}),
    AssetFamily.BUILDING: frozenset(
        {"engine_house", "chemical_plant", "station", "warehouse", "industry"}
    ),
}

ROLLING_FAMILIES = frozenset(
    {AssetFamily.LOCO, AssetFamily.MOW, AssetFamily.PASSENGER, AssetFamily.FREIGHT}
)


class Possession(StrEnum):
    PLANNED = "planned"
    ORDERED = "ordered"
    SHIPPED = "shipped"
    PARKED = "parked"
    RECEIVED = "received"
    MISSED = "missed"


class Status(StrEnum):
    STORED = "stored"
    ACTIVE = "active"
    MAINTENANCE = "maintenance"
    RETIRED = "retired"


@dataclass(frozen=True, slots=True)
class AssetId:
    value: str

    def __post_init__(self) -> None:
        if not _ASSET_ID.fullmatch(self.value):
            raise ValueError("asset id must be one uppercase letter followed by three digits")

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True, slots=True)
class ConsistId:
    value: str

    def __post_init__(self) -> None:
        if not _CONSIST_ID.fullmatch(self.value):
            raise ValueError("consist id must be K followed by three digits")

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True, slots=True)
class Model:
    scale: str | None = None
    maker: str | None = None
    product_number: str | None = None
    catalog_name: str | None = None
    released_on: date | None = None


@dataclass(frozen=True, slots=True)
class Prototype:
    maker: str | None = None
    model: str | None = None
    reporting_mark: str | None = None
    road_number: str | None = None
    attributes: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class Decoder:
    maker: str | None = None
    model: str | None = None
    serial_number: str | None = None


@dataclass(frozen=True, slots=True)
class Control:
    dcc: bool | None = None
    node_id: AssetId | None = None
    decoder: Decoder | None = None
    address: int | None = None
    speed_steps: int | None = None
    sound: bool | None = None
    attributes: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.dcc is True:
            if self.node_id is not None:
                raise ValueError("dcc control cannot reference an accessory node")
            if self.address is not None and self.address < 1:
                raise ValueError("dcc address must be positive")
        elif any(value is not None for value in (self.decoder, self.address, self.speed_steps, self.sound)):
            raise ValueError("decoder, address, speed_steps and sound require dcc=true")
        if self.node_id is not None and not self.node_id.value.startswith("N"):
            raise ValueError("control node_id must start with N")


@dataclass(frozen=True, slots=True)
class Connection:
    bus: str
    channel: int

    def __post_init__(self) -> None:
        _require_snake_case("connection bus", self.bus)
        if self.channel < 0:
            raise ValueError("connection channel cannot be negative")


@dataclass(frozen=True, slots=True)
class Component:
    ref: str
    type: str
    desc: str
    qty: int = 1
    connection: Connection | None = None
    values: dict[str, int | float | str | bool] = field(default_factory=dict)
    spec: dict[str, Any] = field(default_factory=dict)
    maker: str | None = None
    model: str | None = None
    serial_number: str | None = None
    installed_on: date | None = None
    removed_on: date | None = None

    def __post_init__(self) -> None:
        _require_snake_case("component ref", self.ref)
        _require_snake_case("component type", self.type)
        _require_snake_case("component desc", self.desc)
        if self.qty < 1:
            raise ValueError("component qty must be positive")


@dataclass(frozen=True, slots=True)
class Relation:
    rel: str
    asset_id: AssetId
    reason: str

    def __post_init__(self) -> None:
        _require_snake_case("relation", self.rel)
        _require_snake_case("relation reason", self.reason)
        if self.rel != "requires":
            raise ValueError(f"unsupported relation: {self.rel}")


@dataclass(frozen=True, slots=True)
class Media:
    id: int
    type: str
    view: str
    file: str
    thumb: str | None = None
    primary: bool = False
    notes: str | None = None

    def __post_init__(self) -> None:
        if self.id < 1:
            raise ValueError("media id must be positive")
        _require_snake_case("media type", self.type)
        _require_snake_case("media view", self.view)
        if not self.file:
            raise ValueError("media file is required")


@dataclass(frozen=True, slots=True)
class Asset:
    id: AssetId
    family: AssetFamily
    type: str
    label: str | None = None
    model: Model | None = None
    prototype: Prototype | None = None
    control: Control | None = None
    components: tuple[Component, ...] = ()
    relations: tuple[Relation, ...] = ()
    media: tuple[Media, ...] = ()
    notes: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def __post_init__(self) -> None:
        expected_prefix = PREFIXES[self.family]
        if self.id.value[0] != expected_prefix:
            raise ValueError(f"{self.family.value} id must start with {expected_prefix}")
        _require_snake_case("asset type", self.type)
        if self.type not in TYPES[self.family]:
            raise ValueError(f"unsupported {self.family.value} type: {self.type}")
        if self.label is not None and not self.label.strip():
            raise ValueError("label cannot be blank")
        if len({component.ref for component in self.components}) != len(self.components):
            raise ValueError("component refs must be unique within an asset")
        if any(relation.asset_id == self.id for relation in self.relations):
            raise ValueError("asset cannot relate to itself")

    def to_dict(self) -> dict[str, Any]:
        payload = _compact_json(asdict(self))
        payload["id"] = self.id.value
        if self.control is not None and self.control.node_id is not None:
            payload["control"]["node_id"] = self.control.node_id.value
        for relation, serialized in zip(self.relations, payload.get("relations", []), strict=True):
            serialized["asset_id"] = relation.asset_id.value
        return payload


@dataclass(frozen=True, slots=True)
class Lifecycle:
    asset_id: AssetId
    possession: Possession = Possession.PLANNED
    status: Status | None = None
    location: str | None = None
    ordered_on: date | None = None
    shipped_on: date | None = None
    received_on: date | None = None
    retired_on: date | None = None
    revision: int = 1
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def __post_init__(self) -> None:
        if self.revision < 1:
            raise ValueError("lifecycle revision must be positive")
        if self.possession is Possession.RECEIVED and self.status is None:
            raise ValueError("received asset requires a status")
        if self.possession is not Possession.RECEIVED and self.status is not None:
            raise ValueError("only a received asset can have an inventory status")
        if self.status is Status.ACTIVE and not self.location:
            raise ValueError("active asset requires a location")
        if self.status is Status.RETIRED and self.retired_on is None:
            raise ValueError("retired asset requires retired_on")
        if self.retired_on is not None and self.status is not Status.RETIRED:
            raise ValueError("retired_on requires retired status")

    def to_dict(self) -> dict[str, Any]:
        payload = _compact_json(asdict(self))
        payload["asset_id"] = self.asset_id.value
        return payload


@dataclass(frozen=True, slots=True)
class Consist:
    id: ConsistId
    units: tuple[AssetId, ...]
    label: str | None = None
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def __post_init__(self) -> None:
        if not self.units:
            raise ValueError("consist requires at least one unit")
        if len(set(self.units)) != len(self.units):
            raise ValueError("asset cannot occur twice in a consist")
        if self.label is not None and not self.label.strip():
            raise ValueError("label cannot be blank")

    def to_dict(self) -> dict[str, Any]:
        payload = _compact_json(asdict(self))
        payload["id"] = self.id.value
        payload["units"] = [unit.value for unit in self.units]
        return payload


def is_block(location: str | None) -> bool:
    return location is not None and _BLOCK.fullmatch(location) is not None


def _require_snake_case(label: str, value: str) -> None:
    if not _SNAKE_CASE.fullmatch(value):
        raise ValueError(f"{label} must use snake_case")


def _compact_json(value: Any) -> Any:
    if isinstance(value, dict):
        compact: dict[str, Any] = {}
        for key, item in value.items():
            converted = _compact_json(item)
            if converted is not None and converted != {} and converted != []:
                compact[key] = converted
        return compact
    if isinstance(value, (list, tuple)):
        return [_compact_json(item) for item in value]
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, StrEnum):
        return value.value
    return value
