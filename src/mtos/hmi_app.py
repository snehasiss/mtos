"""LAN-facing React and Socket.IO service for human operation."""

from __future__ import annotations

import os
import json
from pathlib import Path

from flask import Flask, jsonify, request, send_from_directory
from flask_socketio import SocketIO, emit

from .hmi.gateway import CoreGateway
from .hmi.service import HmiRejected, HmiService


def create_hmi_app(config=None):
    app = Flask(__name__)
    app.config.update(
        HMI_UI_ROOT=Path(__file__).with_name("control_ui"),
        INTERNAL_TOKEN=os.environ.get("MTOS_INTERNAL_TOKEN", "development-only"),
        CORE_URL="http://127.0.0.1:5303",
        HMI_MONITOR=True,
    )
    app.config.update(config or {})
    service = app.config.get("HMI_SERVICE") or HmiService(
        CoreGateway(app.config["CORE_URL"], app.config["INTERNAL_TOKEN"])
    )
    socketio = SocketIO(
        app, async_mode="threading",
        max_http_buffer_size=64 * 1024, logger=False, engineio_logger=False,
    )
    app.extensions["hmi_service"] = service
    app.extensions["socketio"] = socketio
    ui_root = Path(app.config["HMI_UI_ROOT"])

    @app.after_request
    def headers(response):
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; connect-src 'self' ws: wss:; img-src 'self'; "
            "style-src 'self'; script-src 'self'; frame-ancestors 'none'"
        )
        return response

    @app.get("/")
    def index():
        response = send_from_directory(ui_root, "index.html")
        # The HTML names content-hashed bundles.  Revalidate it so mobile
        # browsers pick up a rebuilt UI instead of retaining an obsolete hash.
        response.headers["Cache-Control"] = "no-cache"
        return response

    @app.get("/control-ui/<path:name>")
    def control_ui(name):
        return send_from_directory(ui_root, name)

    @app.get("/static/<path:name>")
    def shared_static(name):
        return send_from_directory(Path(__file__).with_name("static"), name)

    @app.get("/health")
    def health():
        return jsonify(status="ok", service="mtos_hmi", pid=os.getpid(), instance=os.environ.get("MTOS_INSTANCE"))

    @app.get("/ready")
    def ready():
        try:
            service.snapshot()
            return jsonify(ready=True)
        except Exception as error:
            return jsonify(ready=False, error=str(error)), 503

    @app.get("/api/control")
    def diagnostic_snapshot():
        return jsonify(service.snapshot())

    @socketio.on("connect")
    def connected(auth=None):
        if not service.connect(request.sid):
            return False
        emit("control.snapshot", service.snapshot())

    @socketio.on("disconnect")
    def disconnected():
        service.disconnect(request.sid)

    @socketio.on("control.snapshot.request")
    def snapshot_request(_payload=None):
        return service.snapshot()

    @socketio.on("roster.request")
    def roster_request(_payload=None):
        return {"items": service.locomotives()}

    @socketio.on("devices.request")
    def devices_request(_payload=None):
        return {"items": service.devices()}

    @socketio.on("stationary.request")
    def stationary_request(_payload=None):
        return {"items": service.stationary()}

    @socketio.on("programming.request")
    def programming_request(_payload=None):
        return {"items": service.programming_assets()}

    @socketio.on("control.command")
    def command(value):
        try:
            accepted = service.accept(request.sid, value)
        except (HmiRejected, TypeError, ValueError) as error:
            return {"accepted": False, "error": str(error)}
        event = service.event("command.accepted", accepted["command_id"])
        emit("command.event", event)
        socket_id = request.sid

        def execute():
            result = service.execute(socket_id, accepted)
            socketio.emit("command.event", result, to=socket_id)
            try:
                socketio.emit("control.snapshot", service.snapshot(), to=socket_id)
            except Exception:
                pass

        socketio.start_background_task(execute)
        return {"accepted": True, "command_id": accepted["command_id"], "state": "accepted"}

    if app.config["HMI_MONITOR"]:
        def monitor():
            previous = None
            while True:
                try:
                    snapshot = service.snapshot()
                    encoded = json.dumps(snapshot, sort_keys=True, separators=(",", ":"))
                    if encoded != previous:
                        socketio.emit("control.snapshot", snapshot)
                        previous = encoded
                except Exception:
                    pass
                socketio.sleep(0.25)

        socketio.start_background_task(monitor)

    return app, socketio
