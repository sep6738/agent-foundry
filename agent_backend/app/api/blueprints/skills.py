"""Skill listing, editing, validation, and explicit usage endpoints."""

from __future__ import annotations

import time

from flask import Blueprint, current_app, jsonify, request

from agent_backend.app.api.errors import error
from agent_backend.app.api.schemas import require_fields
from agent_backend.app.observability.events import Event

skills_bp = Blueprint("skills", __name__, url_prefix="/v1/skills")


@skills_bp.get("")
def list_skills():
    runtime_context = current_app.extensions["runtime_context"]
    skills = runtime_context.skill_registry.list_skills(
        runtime_context.settings.project_root,
        user_home=runtime_context.user_home,
    )
    return jsonify({"skills": [meta.__dict__ for meta in skills]})


@skills_bp.post("")
def create_skill():
    data = request.get_json(silent=True) or {}
    name = str(data.get("name", "")).strip()
    content = str(data.get("content", "")).strip()
    missing = require_fields(data, ("name", "content"))
    if missing:
        return error("name and content are required")
    runtime_context = current_app.extensions["runtime_context"]
    validation = runtime_context.skill_registry.validate(content)
    if not validation["ok"]:
        return error("; ".join(validation["errors"]))
    skill = runtime_context.skill_registry.save(
        name,
        content,
        runtime_context.settings.project_root,
        str(data.get("scope", "project")),
        user_home=runtime_context.user_home,
    )
    return jsonify(skill.meta.__dict__), 201


@skills_bp.get("/<name>")
def get_skill(name: str):
    runtime_context = current_app.extensions["runtime_context"]
    skill = runtime_context.skill_registry.get_skill(
        name,
        runtime_context.settings.project_root,
        user_home=runtime_context.user_home,
    )
    if skill is None:
        return error("skill not found", 404)
    return jsonify({"meta": skill.meta.__dict__, "content": skill.content})


@skills_bp.put("/<name>")
def update_skill(name: str):
    data = request.get_json(silent=True) or {}
    content = str(data.get("content", "")).strip()
    if not require_fields(data, ("content",)):
        return error("content is required")
    runtime_context = current_app.extensions["runtime_context"]
    validation = runtime_context.skill_registry.validate(content)
    if not validation["ok"]:
        return error("; ".join(validation["errors"]))
    skill = runtime_context.skill_registry.save(
        name,
        content,
        runtime_context.settings.project_root,
        str(data.get("scope", "project")),
        user_home=runtime_context.user_home,
    )
    return jsonify(skill.meta.__dict__)


@skills_bp.delete("/<name>")
def delete_skill(name: str):
    runtime_context = current_app.extensions["runtime_context"]
    if not runtime_context.skill_registry.delete(
        name,
        runtime_context.settings.project_root,
        user_home=runtime_context.user_home,
    ):
        return error("skill not found", 404)
    return jsonify({"deleted": name})


@skills_bp.post("/<name>/validate")
def validate_skill(name: str):
    data = request.get_json(silent=True) or {}
    runtime_context = current_app.extensions["runtime_context"]
    validation = runtime_context.skill_registry.validate(str(data.get("content", "")))
    return jsonify(validation)


@skills_bp.post("/<name>/use")
def use_skill(name: str):
    data = request.get_json(silent=True) or {}
    session_id = str(data.get("session_id", "")).strip()
    if not session_id:
        return error("session_id is required")
    runtime_context = current_app.extensions["runtime_context"]
    if runtime_context.session_manager.get(session_id) is None:
        return error("session not found", 404)
    skill = runtime_context.skill_registry.get_skill(
        name,
        runtime_context.settings.project_root,
        user_home=runtime_context.user_home,
    )
    if skill is None:
        return error("skill not found", 404)
    started = time.monotonic()
    runtime_context.session_manager.append_entry(
        session_id,
        "session_instruction",
        {"key": f"skill:{name}", "content": skill.content},
    )
    duration_ms = int((time.monotonic() - started) * 1000)
    runtime_context.skill_registry.record_invocation(
        session_id=session_id,
        skill_name=name,
        mode="explicit",
        result="ok",
        duration_ms=duration_ms,
    )
    runtime_context.event_bus.publish(
        Event(
            type="skill_invoked",
            session_id=session_id,
            payload={"skill": name, "mode": "explicit"},
        )
    )
    return jsonify({"skill": name, "injected": True, "content": skill.content}), 201
