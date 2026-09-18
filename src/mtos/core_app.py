"""Loopback API for deterministic MTOS operational Core."""

from __future__ import annotations

import atexit
import hmac
import os

from flask import Flask, abort, jsonify, request
from werkzeug.exceptions import HTTPException

from .core.clients import AssetClient, DccClient, ServiceError
from .core.service import CoreConflict, CoreService
from .roster import data_root


def create_core_app(config=None):
    app = Flask(__name__)
    app.config.update(INTERNAL_TOKEN=os.environ.get("MTOS_INTERNAL_TOKEN", "development-only"))
    app.config.update(config or {})
    service = app.config.get("CORE_SERVICE") or CoreService(
        app.config.get("DATA_ROOT", data_root()),
        AssetClient(app.config.get("ASSET_URL", "http://127.0.0.1:5301"), app.config["INTERNAL_TOKEN"]),
        DccClient(app.config.get("DCC_URL", "http://127.0.0.1:5304"), app.config["INTERNAL_TOKEN"]),
    )
    app.extensions["core_service"] = service
    atexit.register(service.close)

    def body():
        value = request.get_json(silent=False)
        if not isinstance(value, dict):
            raise ValueError("JSON body must be an object")
        return value

    @app.before_request
    def internal_only():
        if request.path != "/health":
            supplied = request.headers.get("X-MTOS-Internal-Token", "")
            if not hmac.compare_digest(supplied, app.config["INTERNAL_TOKEN"]):
                abort(403)

    @app.errorhandler(Exception)
    def errors(error):
        if isinstance(error, HTTPException):
            return jsonify(error=error.description), error.code
        if isinstance(error, CoreConflict):
            return jsonify(error=str(error)), 409
        if isinstance(error, (ValueError, TypeError)):
            return jsonify(error=str(error)), 400
        if isinstance(error, ServiceError):
            return jsonify(error=str(error)), 503
        app.logger.exception("Core request failed")
        return jsonify(error="Internal server error"), 500

    @app.get("/health")
    def health():
        return jsonify(status="ok", service="mtos_core", pid=os.getpid(), instance=os.environ.get("MTOS_INSTANCE"))

    @app.get("/ready")
    def ready():
        usable = service.started and service.dcc_ready
        return jsonify(ready=usable, **service.snapshot()), 200 if usable else 503

    @app.post("/v1/start")
    def start():
        return jsonify(service.start())

    @app.post("/v1/heartbeat")
    def heartbeat():
        return jsonify(service.heartbeat())

    @app.get("/v1/state")
    def state():
        return jsonify(service.snapshot())

    @app.get("/v1/hmi/snapshot")
    def hmi_snapshot():
        return jsonify(service.hmi_snapshot())

    @app.get("/v1/hmi/locomotives")
    def hmi_locomotives():
        return jsonify(items=service.hmi_locomotives())

    @app.get("/v1/hmi/devices")
    def hmi_devices():
        return jsonify(items=service.hmi_devices())

    @app.post("/v1/hmi/commands")
    def hmi_command():
        value = body()
        return jsonify(service.hmi_command(
            value.get("operation"), value.get("payload") or {}, value.get("command_id")
        ))

    @app.post("/v1/main/power")
    def power():
        value = body()
        return jsonify(service.main_power(value.get("on"), value.get("command_id")))

    @app.post("/v1/locomotives/<asset_id>/throttle")
    def throttle(asset_id):
        value = body()
        return jsonify(service.throttle(asset_id, value.get("speed"), value.get("direction"), value.get("command_id")))

    @app.post("/v1/locomotives/<asset_id>/functions/<int:number>")
    def function(asset_id, number):
        value = body()
        return jsonify(service.function(asset_id, number, value.get("active"), value.get("command_id")))

    @app.post("/v1/locomotives/<asset_id>/stop")
    def stop(asset_id):
        value = body()
        return jsonify(service.stop(asset_id, value.get("command_id")))

    @app.post("/v1/emergency-stop")
    def emergency():
        value = body()
        return jsonify(service.emergency_stop(value.get("command_id")))

    @app.post("/v1/resume")
    def resume():
        return jsonify(service.resume())

    return app
