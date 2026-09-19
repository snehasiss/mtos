"""Flask application factory for the MTOS asset library."""

import os
import hmac
import secrets
import sqlite3
import tempfile
from pathlib import Path

from flask import (
    Flask,
    abort,
    jsonify,
    render_template,
    request,
    send_from_directory,
    session,
)
from werkzeug.exceptions import HTTPException

from .assets.model import LOCATIONS, TYPES, Possession, Status
from .image_optimizer import ImageOptimizerBusy
from .roster import Conflict, Roster


def create_app(config=None):
    app = Flask(__name__)
    app.config.update(
        MAX_CONTENT_LENGTH=20 * 1024 * 1024,
        INTERNAL_TOKEN=os.environ.get("MTOS_INTERNAL_TOKEN", "development-only"),
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Strict",
    )
    app.config.update(config or {})
    roster = Roster(app.config.get("DATA_ROOT"))
    app.extensions["roster"] = roster
    secret = roster.root / "db/session.key"
    with roster.lock():
        if not secret.exists():
            with secret.open("x") as stream:
                stream.write(secrets.token_hex(32))
            secret.chmod(0o600)
        app.secret_key = secret.read_text()

    @app.before_request
    def protect_writes():
        if request.method in ("POST", "PUT", "PATCH", "DELETE"):
            if request.path.startswith("/internal/"):
                supplied = request.headers.get("X-MTOS-Internal-Token", "")
                if not hmac.compare_digest(supplied, app.config["INTERNAL_TOKEN"]):
                    abort(403)
                return
            expected = session.get("csrf")
            if not expected or not secrets.compare_digest(
                expected, request.headers.get("X-CSRF-Token", "")
            ):
                abort(
                    403, description="Missing or invalid CSRF token; reload the page."
                )

    @app.after_request
    def headers(response):
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; img-src 'self' blob:; style-src 'self'; script-src 'self'; frame-ancestors 'none'"
        )
        if request.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.errorhandler(Exception)
    def errors(error):
        if isinstance(error, ImageOptimizerBusy):
            return jsonify(error=str(error)), 503
        if isinstance(error, HTTPException):
            return jsonify(error=error.description), error.code
        if isinstance(error, KeyError):
            return jsonify(
                error=f"Asset or required field not found: {error.args[0]}"
            ), 404
        if isinstance(error, (Conflict, sqlite3.IntegrityError)):
            return jsonify(error=str(error)), 409
        if isinstance(error, (ValueError, TypeError)):
            return jsonify(error=str(error)), 400
        app.logger.exception("Roster request failed")
        return jsonify(error="Internal server error"), 500

    @app.get("/")
    def index():
        session.setdefault("csrf", secrets.token_hex(32))
        return render_template("roster.html", csrf=session["csrf"])

    @app.get("/api/session")
    def api_session():
        session.setdefault("csrf", secrets.token_hex(32))
        return jsonify(csrf=session["csrf"])

    @app.get("/health")
    def health():
        with roster.connect() as db:
            db.execute("SELECT 1 FROM asset LIMIT 1")
        return jsonify(
            status="ok",
            service="mtos_asset",
            pid=os.getpid(),
            instance=os.environ.get("MTOS_INSTANCE"),
        )

    @app.get("/api/schema")
    def schema():
        return jsonify(
            families={family.value: sorted(types) for family, types in TYPES.items()},
            possession=[s.value for s in Possession],
            status=[s.value for s in Status],
            locations=list(LOCATIONS),
        )

    @app.get("/api/assets")
    def assets():
        return jsonify(
            roster.search(
                **{
                    k: request.args[k]
                    for k in ("q", "family", "status", "limit", "offset")
                    if k in request.args
                }
            )
        )

    @app.post("/api/assets")
    def add():
        return jsonify(roster.save(request.get_json())), 201

    @app.get("/api/next-asset-id")
    def next_asset_id():
        return jsonify(id=roster.next_asset_id(request.args.get("family", "")))

    @app.get("/api/assets/<asset_id>")
    def get(asset_id):
        return jsonify(roster.get(asset_id))

    @app.patch("/api/assets/<asset_id>")
    def update(asset_id):
        return jsonify(roster.save(request.get_json(), asset_id=asset_id))

    @app.get("/api/assets/<asset_id>/media")
    def media(asset_id):
        return jsonify(roster.get(asset_id)["media"])

    @app.get("/api/assets/<asset_id>/media/<filename>")
    def photo(asset_id, filename):
        images = roster.get(asset_id)["media"]["images"]
        if filename not in {image["filename"] for image in images}:
            abort(404)
        return send_from_directory(
            roster.media_path(asset_id, filename).parent, filename
        )

    @app.post("/api/assets/<asset_id>/media")
    def upload(asset_id):
        image = request.files.get("image")
        if image is None:
            raise ValueError("image upload required")
        sequence = int(request.form["sequence"])
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "upload"
            image.save(source)
            created = roster.put_media(
                asset_id,
                sequence,
                source,
                optimize=True,
            )
        if not created:
            raise Conflict("Image sequence already exists")
        return jsonify(roster.get(asset_id)["media"]), 201

    @app.get("/api/consists")
    def consists():
        return jsonify(items=roster.consists())

    @app.post("/api/consists")
    def add_consist():
        return jsonify(roster.save_consist(request.get_json())), 201

    @app.get("/internal/operating-locomotives")
    def operating_locomotives():
        supplied = request.headers.get("X-MTOS-Internal-Token", "")
        if not hmac.compare_digest(supplied, app.config["INTERNAL_TOKEN"]):
            abort(403)
        items = []
        for asset in roster.search(family="loco", status="active", limit=100)["items"]:
            life, control = asset.get("lifecycle") or {}, asset.get("control") or {}
            if life.get("possession") != "received" or control.get("dcc") is not True:
                continue
            address = control.get("address")
            if type(address) is not int:
                continue
            proto = asset.get("prototype") or {}
            items.append({"id": asset["id"], "reporting_mark": proto.get("reporting_mark"),
                          "road_number": proto.get("road_number"), "prototype": proto.get("model"),
                          "address": address})
        return jsonify(items=items)

    @app.get("/internal/operating-stationary-assets")
    def operating_stationary_assets():
        supplied = request.headers.get("X-MTOS-Internal-Token", "")
        if not hmac.compare_digest(supplied, app.config["INTERNAL_TOKEN"]):
            abort(403)
        items = []
        for family in ("turnout", "signal", "machine"):
            for asset in roster.search(family=family, status="active", limit=100)["items"]:
                life, control = asset.get("lifecycle") or {}, asset.get("control") or {}
                if life.get("possession") != "received" or not control.get("node_id"):
                    continue
                items.append({"id": asset["id"], "family": family, "type": asset["type"],
                              "label": asset.get("label"), "node_id": control["node_id"],
                              "revision": asset["revision"],
                              "configuration_revision": control.get("configuration_revision", asset["revision"]),
                              "actions": control.get("actions", ["operate"] if family == "machine" else [])})
        return jsonify(items=items)

    @app.post("/internal/control-leases")
    def control_leases():
        value = request.get_json()
        return jsonify(leases=roster.acquire_leases(
            value.get("asset_ids"), value.get("expected_revisions") or {},
            value.get("core_session_id"), value.get("core_epoch"), value.get("purpose"),
            value.get("duration_seconds", 30),
        ))

    @app.patch("/api/consists/<consist_id>")
    def update_consist(consist_id):
        return jsonify(roster.save_consist(request.get_json(), consist_id))

    return app
