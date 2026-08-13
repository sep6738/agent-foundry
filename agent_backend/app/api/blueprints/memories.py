"""Memory fact, compression, and consolidation endpoints."""

from __future__ import annotations

from datetime import datetime

from flask import Blueprint, current_app, g, jsonify, request

from agent_backend.app.api.errors import error
from agent_backend.app.api.schemas import require_fields

memories_bp = Blueprint("memories", __name__, url_prefix="/v1/memories")


def _user_id(data: dict | None = None) -> str:
    settings = current_app.config["SETTINGS"]
    explicit = (
        request.headers.get("X-User-Id")
        or request.args.get("user_id")
        or (str((data or {}).get("user_id", "default")) if data else "default")
    )
    if settings.api_keys:
        return getattr(g, "user_id", None) or explicit
    return explicit


@memories_bp.get("")
def search_memories():
    runtime_context = current_app.extensions["runtime_context"]
    query = str(request.args.get("q", "")).strip()
    user_id = _user_id()
    limit = int(request.args.get("limit", 10))
    facts = runtime_context.memory_store.search(user_id, query, limit=limit) if query else []
    return jsonify({"facts": [fact.__dict__ for fact in facts]})


@memories_bp.get("/<memory_id>")
def get_memory(memory_id: str):
    runtime_context = current_app.extensions["runtime_context"]
    fact = runtime_context.memory_store.get(memory_id)
    if fact is None:
        return error("memory not found", 404)
    return jsonify(fact.__dict__)


@memories_bp.post("")
def create_memory():
    data = request.get_json(silent=True) or {}
    subject = str(data.get("subject", "")).strip()
    content = str(data.get("content", "")).strip()
    missing = require_fields(data, ("subject", "content"))
    if missing:
        return error("subject and content are required")
    runtime_context = current_app.extensions["runtime_context"]
    ttl = data.get("ttl")
    ttl_dt = None
    if ttl:
        try:
            ttl_dt = datetime.fromisoformat(str(ttl))
        except ValueError:
            return error("ttl must be an ISO timestamp")
    fact = runtime_context.memory_store.save_fact(
        user_id=_user_id(data),
        session_id=data.get("session_id"),
        subject=subject,
        content=content,
        kind=str(data.get("kind", "fact")),
        tags=data.get("tags") or [],
        keywords=data.get("keywords"),
        scope=str(data.get("scope", "user")),
        importance=float(data.get("importance", 0.5)),
        confidence=float(data.get("confidence", 0.7)),
        ttl=ttl_dt,
    )
    return jsonify(fact.__dict__), 201


@memories_bp.put("/<memory_id>")
def update_memory(memory_id: str):
    data = request.get_json(silent=True) or {}
    content = str(data.get("content", "")).strip()
    if not content:
        return error("content is required")
    runtime_context = current_app.extensions["runtime_context"]
    fact = runtime_context.memory_store.update_fact(memory_id, content)
    if fact is None:
        return error("memory not found", 404)
    return jsonify(fact.__dict__)


@memories_bp.post("/<memory_id>/confirm")
def confirm_memory(memory_id: str):
    runtime_context = current_app.extensions["runtime_context"]
    fact = runtime_context.memory_store.confirm_fact(memory_id)
    if fact is None:
        return error("memory not found", 404)
    return jsonify(fact.__dict__)


@memories_bp.delete("/<memory_id>")
def delete_memory(memory_id: str):
    runtime_context = current_app.extensions["runtime_context"]
    if not runtime_context.memory_store.forget(memory_id):
        return error("memory not found", 404)
    return jsonify({"deleted": memory_id})


@memories_bp.post("/compress")
def compress_memories():
    data = request.get_json(silent=True) or {}
    session_id = str(data.get("session_id", "")).strip()
    if not session_id:
        return error("session_id is required")
    runtime_context = current_app.extensions["runtime_context"]
    if runtime_context.session_manager.get(session_id) is None:
        return error("session not found", 404)
    entries = runtime_context.session_manager.history(session_id)
    messages = [
        {
            "role": entry["payload"].get("role", entry["type"]),
            "content": str(entry["payload"].get("content", "")),
            "id": entry["id"],
        }
        for entry in entries
    ]
    summary = runtime_context.memory_store.summarize(session_id)
    outcome = runtime_context.compressor.compress(
        session_id,
        runtime_context.settings.default_token_budget,
        messages,
        summary,
        trigger=str(data.get("trigger", "manual")),
    )
    return jsonify(
        {
            "result": outcome.result.__dict__,
            "context_messages": outcome.context_messages,
        }
    )


@memories_bp.post("/consolidate")
def consolidate_memories():
    data = request.get_json(silent=True) or {}
    runtime_context = current_app.extensions["runtime_context"]
    result = runtime_context.consolidator.consolidate(
        _user_id(data),
        window=int(data.get("window", 50)),
    )
    return jsonify(result.__dict__)
