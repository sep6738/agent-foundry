"""JSON API error helpers."""

from __future__ import annotations

from flask import jsonify


def error(message: str, status: int = 400):
    return jsonify({"error": message}), status
