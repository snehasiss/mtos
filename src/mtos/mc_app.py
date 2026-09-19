"""Loopback HTTP interface for the MTOS microcontroller adapter."""

from __future__ import annotations

import atexit
import hmac
import os

from flask import Flask, abort, jsonify, request
from werkzeug.exceptions import HTTPException

from .mc.mqtt import PahoMqttTransport
from .mc.service import McBusy, McConflict, McService, StaleCoreSession
from .roster import data_root


def create_mc_app(config=None):
    app = Flask(__name__)
    app.config.update(INTERNAL_TOKEN=os.environ.get("MTOS_INTERNAL_TOKEN", "development-only"),
                      MQTT_ENABLED=os.environ.get("MTOS_MQTT_ENABLED") == "1")
    app.config.update(config or {})
    service = app.config.get("MC_SERVICE") or McService(app.config.get("DATA_ROOT", data_root()))
    if app.config["MQTT_ENABLED"] and app.config.get("MC_SERVICE") is None:
        service.transport = PahoMqttTransport(
            host=os.environ.get("MTOS_MQTT_HOST", "127.0.0.1"),
            port=int(os.environ.get("MTOS_MQTT_PORT", "1883")),
            username=os.environ.get("MTOS_MQTT_USERNAME"),
            password=os.environ.get("MTOS_MQTT_PASSWORD"),
            on_message=service.handle_mqtt,
        )
    app.extensions["mc_service"] = service
    atexit.register(service.close)

    def body():
        value = request.get_json(silent=False)
        if not isinstance(value, dict): raise ValueError("JSON body must be an object")
        return value

    @app.before_request
    def internal_only():
        if request.path != "/health":
            if not hmac.compare_digest(request.headers.get("X-MTOS-Internal-Token", ""), app.config["INTERNAL_TOKEN"]):
                abort(403)

    @app.errorhandler(Exception)
    def errors(error):
        if isinstance(error, HTTPException): return jsonify(error=error.description), error.code
        if isinstance(error, (StaleCoreSession, McConflict)): return jsonify(error=str(error)), 409
        if isinstance(error, McBusy): return jsonify(error=str(error)), 503
        if isinstance(error, KeyError): return jsonify(error="execution not found"), 404
        if isinstance(error, (ValueError, TypeError)): return jsonify(error=str(error)), 400
        if isinstance(error, (RuntimeError, OSError)): return jsonify(error=str(error)), 503
        app.logger.exception("MC request failed")
        return jsonify(error="Internal server error"), 500

    @app.get("/health")
    def health(): return jsonify(status="ok", service="mtos_mc", pid=os.getpid(), instance=os.environ.get("MTOS_INSTANCE"))

    @app.get("/ready")
    def ready():
        state = service.snapshot()
        usable = bool(state["core"] and not state["core"]["stale"] and state["broker"] == "connected")
        return jsonify(ready=usable, **state), 200 if usable else 503

    @app.get("/v1/state")
    def state(): return jsonify(service.snapshot())

    @app.get("/v1/nodes")
    def nodes(): return jsonify(items=service.nodes())

    @app.post("/v1/core/session")
    def session():
        value = body(); return jsonify(service.establish_core_session(value.get("session_id"), value.get("epoch")))

    @app.post("/v1/core/heartbeat")
    def heartbeat():
        value = body(); return jsonify(service.heartbeat(value.get("session_id"), value.get("epoch")))

    @app.post("/v1/executions")
    def submit(): return jsonify(service.submit(body())), 202

    @app.get("/v1/executions/<execution_id>")
    def execution(execution_id): return jsonify(service.execution(execution_id))

    @app.post("/v1/executions/<execution_id>/cancel")
    def cancel(execution_id): return jsonify(service.cancel(execution_id))

    @app.post("/v1/executions/<execution_id>/reconcile")
    def reconcile(execution_id):
        value = body(); return jsonify(service.reconcile(execution_id, value.get("resolution"), value.get("detail")))

    return app
