"""Session CRUD, history, abort, compact, and human approval."""

from __future__ import annotations

from flask import Blueprint, current_app, g, jsonify, request

from agent_backend.app.api.errors import error
from agent_backend.app.api.schemas import parse_bool
from agent_backend.app.services import ConversationService, SessionService

sessions_bp = Blueprint("sessions", __name__, url_prefix="/v1/sessions")


def _services():
    context = current_app.extensions["runtime_context"]
    return SessionService(context), ConversationService(context)


@sessions_bp.get("")
def list_sessions():
    session_service, _ = _services()
    settings = current_app.config["SETTINGS"]
    if settings.api_keys:
        user_id = getattr(g, "user_id", None) or request.args.get("user_id")
    else:
        user_id = request.args.get("user_id") or request.headers.get("X-User-Id")
    return jsonify({"sessions": session_service.list(user_id)})


@sessions_bp.post("")
def create_session():
    data = request.get_json(silent=True) or {}
    runtime_context = current_app.extensions["runtime_context"]
    session_service, _ = _services()
    settings = current_app.config["SETTINGS"]
    if settings.api_keys:
        user_id = getattr(g, "user_id", None) or str(data.get("user_id", "default"))
    else:
        user_id = request.headers.get("X-User-Id") or str(data.get("user_id", "default"))
    project_id = data.get("project_id")
    if project_id:
        project = runtime_context.project_manager.get(str(project_id))
        if project is None or project.user_id != user_id:
            return error("project not found", 404)
    return jsonify(
        session_service.create(
            user_id,
            str(data.get("title", "Untitled")),
            project_id=str(project_id) if project_id else None,
        )
    ), 201


@sessions_bp.get("/<session_id>")
def get_session(session_id: str):
    session_service, _ = _services()
    session = session_service.get(session_id)
    if session is None:
        return error("session not found", 404)
    return jsonify(session)


@sessions_bp.delete("/<session_id>")
def delete_session(session_id: str):
    session_service, _ = _services()
    if not session_service.delete(session_id):
        return error("session not found", 404)
    return jsonify({"session_id": session_id, "status": "deleted"})


@sessions_bp.get("/<session_id>/history")
def history(session_id: str):
    session_service, _ = _services()
    if session_service.get(session_id) is None:
        return error("session not found", 404)
    return jsonify({"session_id": session_id, "entries": session_service.history(session_id)})


@sessions_bp.get("/<session_id>/events")
def session_events(session_id: str):
    session_service, _ = _services()
    if session_service.get(session_id) is None:
        return error("session not found", 404)
    return jsonify({"session_id": session_id, "events": session_service.events(session_id)})


@sessions_bp.post("/<session_id>/abort")
def abort_session(session_id: str):
    _, conversation_service = _services()
    if not conversation_service.abort(session_id):
        return error("session not found", 404)
    return jsonify({"session_id": session_id, "status": "aborted"})


@sessions_bp.post("/<session_id>/compact")
def compact(session_id: str):
    _, conversation_service = _services()
    result = conversation_service.compact(session_id)
    if result is None:
        return error("session not found", 404)
    return jsonify(result)


@sessions_bp.post("/<session_id>/human/approve")
def human_approve(session_id: str):
    session_service, conversation_service = _services()
    session = session_service.get(session_id)
    if session is None:
        return error("session not found", 404)
    data = request.get_json(silent=True) or {}
    approved = parse_bool(data.get("approved", True), default=True)
    result = conversation_service.resume_turn(
        session_id=session_id,
        approved=approved,
        thread_id=session["thread_id"],
        trace_id=getattr(g, "request_id", None),
    )
    if result.get("error"):
        return error(result["error"], 409)
    return jsonify(result)
