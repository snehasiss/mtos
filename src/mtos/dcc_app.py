"""Loopback HTTP interface for the MTOS DCC adapter."""

from __future__ import annotations

import atexit
import hmac
import os

from flask import Flask, abort, jsonify, request
from werkzeug.exceptions import HTTPException

from .dcc.service import DccBusy, DccService, StaleCoreSession


def create_dcc_app(config=None):
    app = Flask(__name__)
    app.config.update(INTERNAL_TOKEN=os.environ.get("MTOS_INTERNAL_TOKEN", "development-only"))
    app.config.update(config or {})
    service = app.config.get("DCC_SERVICE") or DccService()
    app.extensions["dcc_service"] = service
    atexit.register(service.close)

    def body():
        value = request.get_json(silent=False)
        if not isinstance(value, dict):
            raise ValueError("JSON body must be an object")
        return value

    @app.before_request
    def internal_only():
        if request.method != "GET":
            supplied = request.headers.get("X-MTOS-Internal-Token", "")
            if not hmac.compare_digest(supplied, app.config["INTERNAL_TOKEN"]):
                abort(403)

    @app.errorhandler(Exception)
    def errors(error):
        if isinstance(error, HTTPException):
            return jsonify(error=error.description), error.code
        if isinstance(error, StaleCoreSession):
            return jsonify(error=str(error)), 409
        if isinstance(error, DccBusy):
            return jsonify(error=str(error)), 503
        if isinstance(error, (ValueError, TypeError)):
            return jsonify(error=str(error)), 400
        if isinstance(error, (RuntimeError, OSError, TimeoutError)):
            return jsonify(error=str(error)), 503
        app.logger.exception("DCC request failed")
        return jsonify(error="Internal server error"), 500

    @app.get("/health")
    def health():
        return jsonify(status="ok", service="mtos_dcc", pid=os.getpid(), instance=os.environ.get("MTOS_INSTANCE"))

    @app.get("/ready")
    def ready():
        state = service.snapshot()
        usable = state["core"] is not None and not state["core"]["stale"]
        return jsonify(ready=usable, **state), 200 if usable else 503

    @app.get("/v1/state")
    def state():
        service.check_watchdog()
        return jsonify(service.snapshot())

    @app.get("/v1/devices")
    def devices():
        return jsonify(items=service.devices())

    @app.post("/v1/core/session")
    def session():
        value = body()
        return jsonify(service.establish_core_session(value.get("session_id"), value.get("epoch")))

    @app.post("/v1/core/heartbeat")
    def heartbeat():
        value = body()
        return jsonify(service.heartbeat(value.get("session_id"), value.get("epoch")))

    @app.post("/v1/device/connect")
    def connect():
        value = body()
        service.validate(value, asset_required=False)
        selection = value.get("selection_id") or value.get("port")
        candidates = {item["selection_id"]: item["port"] for item in service.devices()}
        if selection not in candidates:
            raise ValueError("selected serial device is unavailable")
        return jsonify(service.station.connect(candidates[selection]))

    @app.post("/v1/device/disconnect")
    def disconnect():
        value = body()
        service.validate(value, asset_required=False)
        return jsonify(service.station.disconnect())

    @app.post("/v1/main/power")
    def power():
        value = body()
        if type(value.get("on")) is not bool:
            raise ValueError("on must be boolean")
        return jsonify(service.execute(value, "main_power", lambda: service.station.set_main_power(value["on"]), asset_required=False))

    @app.post("/v1/locomotives/<int:address>/throttle")
    def throttle(address):
        value = body()
        return jsonify(service.execute(value, "throttle", lambda: service.station.throttle(address, value.get("speed"), value.get("direction"))))

    @app.post("/v1/locomotives/<int:address>/functions/<int:number>")
    def function(address, number):
        value = body()
        if type(value.get("active")) is not bool:
            raise ValueError("active must be boolean")
        return jsonify(service.execute(value, "function", lambda: service.station.function(address, number, value["active"])))

    @app.post("/v1/locomotives/<int:address>/stop")
    def stop(address):
        value = body()
        return jsonify(service.execute(value, "stop", lambda: service.station.stop(address, value.get("direction", "forward"))))

    @app.post("/v1/emergency-stop")
    def emergency():
        return jsonify(service.emergency_stop())

    return app
