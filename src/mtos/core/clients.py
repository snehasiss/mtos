"""Versioned service clients used by Core; no browser-facing protocol here."""

from __future__ import annotations

import json
import urllib.error
import urllib.request


class ServiceError(RuntimeError):
    pass


class JsonClient:
    def __init__(self, base_url, token):
        self.base_url = base_url.rstrip("/")
        self.token = token

    def request(self, method, path, payload=None, *, timeout=2):
        data = None if payload is None else json.dumps(payload).encode()
        request = urllib.request.Request(
            self.base_url + path,
            data=data,
            method=method,
            headers={"Content-Type": "application/json", "X-MTOS-Internal-Token": self.token},
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return json.load(response)
        except urllib.error.HTTPError as error:
            try:
                detail = json.load(error).get("error")
            except Exception:
                detail = str(error)
            raise ServiceError(detail) from error
        except OSError as error:
            raise ServiceError(str(error)) from error


class DccClient(JsonClient):
    def session(self, session_id, epoch):
        return self.request("POST", "/v1/core/session", {"session_id": session_id, "epoch": epoch})

    def heartbeat(self, session_id, epoch):
        return self.request("POST", "/v1/core/heartbeat", {"session_id": session_id, "epoch": epoch})

    def command(self, path, envelope):
        return self.request("POST", path, envelope)

    def emergency_stop(self):
        return self.request("POST", "/v1/emergency-stop", {})

    def state(self):
        return self.request("GET", "/v1/state")

    def devices(self):
        return self.request("GET", "/v1/devices")["items"]

    def program_address(self, envelope):
        return self.request("POST", "/v1/programming/address", envelope, timeout=100)


class McClient(JsonClient):
    def session(self, session_id, epoch):
        return self.request("POST", "/v1/core/session", {"session_id": session_id, "epoch": epoch})

    def heartbeat(self, session_id, epoch):
        return self.request("POST", "/v1/core/heartbeat", {"session_id": session_id, "epoch": epoch})

    def state(self):
        return self.request("GET", "/v1/state")

    def nodes(self):
        return self.request("GET", "/v1/nodes")["items"]

    def submit(self, envelope):
        return self.request("POST", "/v1/executions", envelope)

    def execution(self, execution_id):
        return self.request("GET", f"/v1/executions/{execution_id}")


class AssetClient(JsonClient):
    def get(self, asset_id):
        return self.request("GET", f"/api/assets/{asset_id}")

    def acquire_lease(self, asset_id, revision, session_id, epoch, purpose):
        return self.request(
            "POST", "/internal/control-leases",
            {"asset_ids": [asset_id], "expected_revisions": {asset_id: revision},
             "core_session_id": session_id, "core_epoch": epoch,
             "purpose": purpose, "duration_seconds": 30},
        )["leases"][0]

    def locomotives(self):
        return self.request("GET", "/internal/operating-locomotives")["items"]

    def stationary(self):
        return self.request("GET", "/internal/operating-stationary-assets")["items"]

    def update_programmed_address(self, asset_id, revision, address):
        return self.request(
            "PATCH", f"/internal/assets/{asset_id}/programmed-address",
            {"revision": revision, "address": address},
        )
