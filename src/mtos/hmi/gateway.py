"""Core-facing gateway used by the HMI; hardware is never addressed directly."""

from __future__ import annotations

from ..core.clients import JsonClient


class CoreGateway(JsonClient):
    def snapshot(self):
        return self.request("GET", "/v1/hmi/snapshot")

    def locomotives(self):
        return self.request("GET", "/v1/hmi/locomotives")["items"]

    def devices(self):
        return self.request("GET", "/v1/hmi/devices")["items"]

    def command(self, operation, payload, command_id):
        return self.request(
            "POST", "/v1/hmi/commands",
            {"operation": operation, "payload": payload, "command_id": command_id},
        )
