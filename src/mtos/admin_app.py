"""LAN-facing, authenticated MTOS administration interface."""

from __future__ import annotations

import hmac
import os
import secrets
from pathlib import Path

from flask import Flask, abort, jsonify, render_template, request, session
from werkzeug.exceptions import HTTPException

from .admin.service import AdminBusy, AdminService
from .roster import data_root


def create_admin_app(config=None):
    app = Flask(__name__)
    app.config.update(
        ADMIN_TOKEN=os.environ.get("MTOS_ADMIN_TOKEN"),
        SECRET_KEY=os.environ.get("MTOS_ADMIN_SECRET"),
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Strict",
    )
    app.config.update(config or {})
    if not app.config["ADMIN_TOKEN"] or not app.config["SECRET_KEY"]:
        raise RuntimeError("MTOS_ADMIN_TOKEN and MTOS_ADMIN_SECRET are required")
    root = Path(app.config.get("PROJECT_ROOT", Path(__file__).resolve().parents[2]))
    service = app.config.get("ADMIN_SERVICE") or AdminService(root, app.config.get("DATA_ROOT", data_root()))
    app.extensions["admin_service"] = service

    @app.errorhandler(Exception)
    def errors(error):
        if isinstance(error, HTTPException): return jsonify(error=error.description), error.code
        if isinstance(error, KeyError): return jsonify(error="Administrative job not found"), 404
        if isinstance(error, AdminBusy): return jsonify(error=str(error)), 409
        if isinstance(error, (ValueError, RuntimeError, OSError)): return jsonify(error=str(error)), 400
        app.logger.exception("Administrative request failed")
        return jsonify(error="Internal server error"), 500

    @app.after_request
    def headers(response):
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Cache-Control"] = "no-store"
        response.headers["Content-Security-Policy"] = "default-src 'self'; img-src 'self'; style-src 'self'; script-src 'self'; frame-ancestors 'none'"
        return response

    @app.get("/")
    def index(): return render_template("admin.html")

    @app.get("/health")
    def health(): return jsonify(status="ok", service="mtos_admin", pid=os.getpid(), instance=os.environ.get("MTOS_INSTANCE"))

    @app.post("/api/login")
    def login():
        supplied = (request.get_json(silent=True) or {}).get("token", "")
        if not hmac.compare_digest(supplied, app.config["ADMIN_TOKEN"]): abort(403)
        session["admin"] = True
        session["csrf"] = secrets.token_hex(24)
        return jsonify(authenticated=True, csrf=session["csrf"])

    @app.before_request
    def protect():
        if request.path in {"/", "/health", "/api/login"} or request.path.startswith("/static/"): return
        if session.get("admin") is not True: abort(401)
        if request.method not in {"GET", "HEAD", "OPTIONS"} and not hmac.compare_digest(
            request.headers.get("X-CSRF-Token", ""), session.get("csrf", "")
        ): abort(403)

    @app.get("/api/status")
    def status(): return jsonify(service.status())

    @app.post("/api/actions/<operation>")
    def action(operation): return jsonify(service.submit(operation, request.get_json(silent=True) or {})), 202

    @app.get("/api/jobs/<job_id>")
    def job(job_id): return jsonify(service.job(job_id))

    return app
