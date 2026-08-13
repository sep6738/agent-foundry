"""Optional API-key auth and request tracing middleware."""

from __future__ import annotations

import uuid

from flask import Flask, g, jsonify, request

from agent_backend.app.auth import APIKeyAuthenticator


def register_middleware(app: Flask) -> None:
    authenticator = APIKeyAuthenticator(
        api_keys=app.config["SETTINGS"].api_keys,
        key_users=app.config["SETTINGS"].api_key_users,
    )

    @app.before_request
    def authenticate() -> tuple | None:
        g.request_id = request.headers.get("X-Request-Id") or f"req_{uuid.uuid4().hex[:16]}"
        result = authenticator.authenticate(
            header_key=request.headers.get("X-API-Key"),
            authorization=request.headers.get("Authorization"),
            header_user=request.headers.get("X-User-Id"),
        )
        if result.error:
            return jsonify({"error": "unauthorized"}), 401
        g.user_id = result.user_id or "default"
        return None
