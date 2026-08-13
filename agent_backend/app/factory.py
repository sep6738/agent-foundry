"""Flask application factory."""

from __future__ import annotations

from flask import Flask, jsonify

from agent_backend.app.config import Settings
from agent_backend.app.core import RuntimeContext
from agent_backend.app.storage.database import Database


def create_app(settings: Settings | None = None) -> Flask:
    settings = settings or Settings()
    app = Flask(__name__)
    app.config["SETTINGS"] = settings

    db = Database(settings.database_url)
    db.init()
    app.extensions["database"] = db
    app.extensions["runtime_context"] = RuntimeContext.from_settings(settings, db)

    from agent_backend.app.api import register_blueprints
    from agent_backend.app.api.middleware import register_middleware

    register_blueprints(app)
    register_middleware(app)

    @app.errorhandler(404)
    def not_found(_error):
        return jsonify({"error": "not_found"}), 404

    @app.errorhandler(500)
    def server_error(_error):
        return jsonify({"error": "internal_error"}), 500

    return app
