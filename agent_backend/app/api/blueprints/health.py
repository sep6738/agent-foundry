"""Health and metrics endpoints."""

from __future__ import annotations

from flask import Blueprint, current_app, jsonify
from sqlalchemy import func, select

from agent_backend.app.storage.models import Event, MemoryFact, Session, ToolCall

health_bp = Blueprint("health", __name__)


@health_bp.get("/health")
def health():
    return jsonify({"status": "ok"})


@health_bp.get("/metrics")
def metrics():
    db = current_app.extensions["database"]
    with db.session() as session:
        counts = {
            "sessions": session.scalar(select(func.count(Session.id))) or 0,
            "tool_calls": session.scalar(select(func.count(ToolCall.id))) or 0,
            "events": session.scalar(select(func.count(Event.id))) or 0,
            "memory_facts": session.scalar(select(func.count(MemoryFact.id))) or 0,
        }
    return jsonify({"requests": counts["events"], **counts})
