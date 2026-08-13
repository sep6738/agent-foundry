"""Project and session instruction inspection/injection/reload endpoints."""

from __future__ import annotations

from pathlib import Path

from flask import Blueprint, current_app, jsonify, request

from agent_backend.app.api.errors import error
from agent_backend.app.observability.events import Event
from agent_backend.app.services import SessionService

instructions_bp = Blueprint("instructions", __name__, url_prefix="/v1")


def _load_bundle(runtime_context):
    return runtime_context.instruction_loader.load(
        runtime_context.settings.project_root,
        user_home=runtime_context.user_home,
        trusted_roots=tuple(Path(root) for root in runtime_context.settings.trusted_project_roots),
    )


@instructions_bp.get("/instructions")
def list_instructions():
    runtime_context = current_app.extensions["runtime_context"]
    bundle = _load_bundle(runtime_context)
    return jsonify({"files": [f.path for f in bundle.files], "rendered": bundle.render()})


@instructions_bp.post("/instructions/reload")
def reload_instructions():
    runtime_context = current_app.extensions["runtime_context"]
    runtime_context.instruction_loader.reload()
    bundle = _load_bundle(runtime_context)
    runtime_context.event_bus.publish(
        Event(
            type="instruction_loaded",
            payload={"files": [f.path for f in bundle.files]},
        )
    )
    return jsonify({"files": [f.path for f in bundle.files]})


@instructions_bp.get("/sessions/<session_id>/instructions")
def get_session_instructions(session_id: str):
    runtime_context = current_app.extensions["runtime_context"]
    session_service = SessionService(runtime_context)
    if session_service.get(session_id) is None:
        return error("session not found", 404)
    return jsonify(
        {
            "session_id": session_id,
            "instructions": session_service.get_instructions(session_id),
        }
    )


@instructions_bp.post("/sessions/<session_id>/instructions")
def inject_instruction(session_id: str):
    data = request.get_json(silent=True) or {}
    content = str(data.get("content", "")).strip()
    if not content:
        return error("content is required")
    runtime_context = current_app.extensions["runtime_context"]
    session_service = SessionService(runtime_context)
    if session_service.get(session_id) is None:
        return error("session not found", 404)
    key = str(data.get("key") or "")
    result = session_service.inject_instruction(session_id, content, key=key or None)
    return jsonify(result), 201


@instructions_bp.delete("/sessions/<session_id>/instructions/<key>")
def remove_instruction(session_id: str, key: str):
    runtime_context = current_app.extensions["runtime_context"]
    session_service = SessionService(runtime_context)
    if session_service.get(session_id) is None:
        return error("session not found", 404)
    if not session_service.remove_instruction(session_id, key):
        return error("instruction not found", 404)
    return jsonify({"session_id": session_id, "key": key, "removed": True})
