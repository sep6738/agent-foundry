"""Project folder registration and management endpoints."""

from __future__ import annotations

from flask import Blueprint, current_app, g, jsonify, request

from agent_backend.app.api.errors import error

projects_bp = Blueprint("projects", __name__, url_prefix="/v1/projects")


def _user_id(data: dict | None = None) -> str:
    settings = current_app.config["SETTINGS"]
    explicit = request.headers.get("X-User-Id") or (
        str((data or {}).get("user_id", "default")) if data else "default"
    )
    if settings.api_keys:
        return getattr(g, "user_id", None) or explicit
    return explicit


def _serialize(project) -> dict:
    return {
        "id": project.id,
        "user_id": project.user_id,
        "name": project.name,
        "path": project.path,
        "status": project.status,
        "created_at": project.created_at.isoformat(),
        "updated_at": project.updated_at.isoformat(),
    }


@projects_bp.get("")
def list_projects():
    manager = current_app.extensions["runtime_context"].project_manager
    user_id = request.args.get("user_id") or _user_id()
    return jsonify({"projects": [_serialize(project) for project in manager.list(user_id)]})


@projects_bp.post("")
def create_project():
    data = request.get_json(silent=True) or {}
    name = str(data.get("name", "")).strip()
    path = str(data.get("path", "")).strip()
    if not path:
        return error("path is required")
    manager = current_app.extensions["runtime_context"].project_manager
    try:
        project = manager.create(_user_id(data), name, path)
    except ValueError as exc:
        return error(str(exc))
    return jsonify(_serialize(project)), 201


@projects_bp.get("/<project_id>")
def get_project(project_id: str):
    manager = current_app.extensions["runtime_context"].project_manager
    project = manager.get(project_id)
    if project is None:
        return error("project not found", 404)
    return jsonify(_serialize(project))


@projects_bp.delete("/<project_id>")
def delete_project(project_id: str):
    manager = current_app.extensions["runtime_context"].project_manager
    if not manager.delete(project_id):
        return error("project not found", 404)
    return jsonify({"deleted": project_id})
