"""Typed MC protocol values independent of Flask and MQTT libraries."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass


TERMINAL = {"completed", "rejected", "failed", "expired", "cancelled"}
OPERATIONS = {
    "turnout.set": {"straight", "diverging"},
    "signal.set": {"stop", "slow", "go"},
}


def canonical_hash(value: dict) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True, slots=True)
class ExecutionRequest:
    command_id: str
    execution_id: str
    core_session_id: str
    core_epoch: int
    asset_id: str
    asset_revision: int
    configuration_revision: int
    lease_id: str
    fencing_token: int
    node_id: str
    operation: str
    value: str
    expires_at: str
    resources: tuple[str, ...] = ()

    @classmethod
    def from_dict(cls, value):
        resources = value.get("resources") or []
        if not isinstance(resources, list) or any(x not in {"servo", "machine"} for x in resources):
            raise ValueError("resources must contain only servo or machine")
        request = cls(
            **{name: value.get(name) for name in (
                "command_id", "execution_id", "core_session_id", "core_epoch",
                "asset_id", "asset_revision", "configuration_revision", "lease_id",
                "fencing_token", "node_id", "operation", "value", "expires_at",
            )},
            resources=tuple(sorted(set(resources))),
        )
        request.validate()
        return request

    def validate(self):
        identifiers = (self.command_id, self.execution_id, self.core_session_id,
                       self.asset_id, self.lease_id, self.node_id, self.expires_at)
        if not all(isinstance(x, str) and x for x in identifiers):
            raise ValueError("execution identifiers and expires_at are required")
        for name in ("core_epoch", "asset_revision", "configuration_revision", "fencing_token"):
            if type(getattr(self, name)) is not int or getattr(self, name) < 1:
                raise ValueError(f"{name} must be a positive integer")
        if self.operation in OPERATIONS and self.value not in OPERATIONS[self.operation]:
            raise ValueError(f"unsupported {self.operation} value")
        if self.operation == "machine.execute" and not self.value:
            raise ValueError("machine action required")
        if self.operation not in {*OPERATIONS, "machine.execute"}:
            raise ValueError("unsupported MC operation")
        required = "servo" if self.operation == "turnout.set" else "machine" if self.operation == "machine.execute" else None
        if required and required not in self.resources:
            raise ValueError(f"{self.operation} requires {required} resource")

    def payload(self):
        return {name: getattr(self, name) for name in self.__dataclass_fields__}

    @property
    def payload_hash(self):
        value = self.payload()
        value["resources"] = list(self.resources)
        return canonical_hash(value)
