"""Flask application for MTOS low-level asset control."""

from __future__ import annotations

import os
import secrets
import sqlite3
from pathlib import Path

from flask import Flask, abort, jsonify, request, send_from_directory, session
from werkzeug.exceptions import HTTPException

from .control import ControlService
from .roster import Conflict, data_root


def create_control_app(config=None):
    app = Flask(__name__)
    app.config.update(
        SESSION_COOKIE_NAME="mtos_control_session",
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Strict",
    )
    app.config.update(config or {})
    root = app.config.get("DATA_ROOT", data_root())
    ui_root = Path(
        app.config.get("CONTROL_UI_ROOT", Path(__file__).with_name("control_ui"))
    )
    service = app.config.get("CONTROL_SERVICE") or ControlService(root)
    app.extensions["control_service"] = service
    secret = service.repository.roster.root / "db/control-session.key"
    with service.repository.roster.lock():
        if not secret.exists():
            secret.write_text(secrets.token_hex(32))
            secret.chmod(0o600)
    app.secret_key = secret.read_text()

    @app.before_request
    def protect_writes():
        if request.method in ("POST", "PUT", "PATCH", "DELETE"):
            expected = session.get("csrf")
            if not expected or not secrets.compare_digest(
                expected, request.headers.get("X-CSRF-Token", "")
            ):
                abort(403, description="Missing or invalid CSRF token; reload the page.")

    @app.after_request
    def headers(response):
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; img-src 'self'; style-src 'self'; "
            "script-src 'self'; frame-ancestors 'none'"
        )
        if request.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.errorhandler(Exception)
    def errors(error):
        if isinstance(error, HTTPException):
            return jsonify(error=error.description), error.code
        if isinstance(error, KeyError):
            return jsonify(error=f"Asset not found: {error.args[0]}"), 404
        if isinstance(error, Conflict):
            return jsonify(error=str(error)), 409
        if isinstance(error, (ValueError, TypeError)):
            return jsonify(error=str(error)), 400
        if isinstance(error, (RuntimeError, OSError, TimeoutError)):
            return jsonify(error=str(error)), 503
        if isinstance(error, sqlite3.Error):
            return jsonify(error="Control database error"), 500
        app.logger.exception("Control request failed")
        return jsonify(error="Internal server error"), 500

    def body():
        value = request.get_json(silent=False)
        if not isinstance(value, dict):
            raise ValueError("JSON body must be an object")
        return value

    def generation(value):
        if not isinstance(value.get("generation"), str):
            raise ValueError("generation is required")
        return value["generation"]

    @app.get("/")
    def index():
        session.setdefault("csrf", secrets.token_hex(32))
        return send_from_directory(ui_root, "index.html")

    @app.get("/control-ui/<path:name>")
    def control_ui(name):
        return send_from_directory(ui_root, name)

    @app.get("/health")
    def health():
        return jsonify(
            status="ok", service="asset_control", pid=os.getpid(),
            instance=os.environ.get("MTOS_INSTANCE"),
        )

    @app.get("/api/session")
    def api_session():
        session.setdefault("csrf", secrets.token_hex(32))
        return jsonify(csrf=session["csrf"], **service.snapshot())

    @app.get("/api/control")
    def control():
        return jsonify(service.snapshot())

    @app.get("/api/devices")
    def devices():
        return jsonify(items=service.devices())

    @app.get("/api/locomotives")
    def locomotives():
        return jsonify(items=service.repository.locomotives())

    @app.post("/api/device/connect")
    def connect():
        value = body()
        return jsonify(service.connect(value.get("selection_id")))

    @app.post("/api/device/disconnect")
    def disconnect():
        return jsonify(service.disconnect())

    @app.post("/api/main/power")
    def power():
        value = body()
        if type(value.get("on")) is not bool:
            raise ValueError("on must be boolean")
        return jsonify(service.main_power(value["on"], generation(value)))

    @app.post("/api/locomotives/<asset_id>/throttle")
    def throttle(asset_id):
        value = body()
        return jsonify(service.throttle(asset_id, value.get("speed"), value.get("direction"), generation(value)))

    @app.post("/api/locomotives/<asset_id>/functions/<int:number>")
    def function(asset_id, number):
        value = body()
        if type(value.get("active")) is not bool:
            raise ValueError("active must be boolean")
        return jsonify(service.function(asset_id, number, value["active"], generation(value)))

    @app.post("/api/locomotives/<asset_id>/stop")
    def stop(asset_id):
        return jsonify(service.stop(asset_id))

    @app.post("/api/emergency-stop")
    def emergency_stop():
        return jsonify(service.emergency_stop())

    @app.post("/api/resume")
    def resume():
        value = body()
        return jsonify(service.resume(generation(value)))

    @app.post("/api/locomotives/<asset_id>/release")
    def release(asset_id):
        return jsonify(service.release(asset_id))

    return app
