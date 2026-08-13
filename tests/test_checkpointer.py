"""Durable LangGraph checkpoint behavior across runtime instances."""

from __future__ import annotations

from pathlib import Path

from agent_backend.app.config import Settings
from agent_backend.app.core.context import RuntimeContext
from agent_backend.app.core.runtime import AgentRuntime
from agent_backend.app.storage.database import Database


def test_checkpoint_survives_new_runtime_instance(settings: Settings, db: Database) -> None:
    context = RuntimeContext.from_settings(settings, db)
    session = context.session_manager.create("u1", "durable")
    AgentRuntime(context).run_turn(
        session_id=session.id,
        user_id="u1",
        text="list directory",
        thread_id=session.thread_id,
    )
    second_context = RuntimeContext.from_settings(settings, db)
    result = AgentRuntime(second_context).run_turn(
        session_id=session.id,
        user_id="u1",
        text="read AGENTS.md",
        thread_id=session.thread_id,
    )
    assert "Repository Guidelines" in result["response"]


def test_interrupt_checkpoint_resumes_in_new_runtime(tmp_path: Path) -> None:
    db = Database(f"sqlite:///{tmp_path / 'hitl.db'}")
    db.init()
    settings = Settings(
        app_env="test",
        database_url=db.url,
        model_provider="stub",
        project_root=tmp_path,
        audit_level=1,
    )
    context = RuntimeContext.from_settings(settings, db)
    session = context.session_manager.create("u1", "hitl")
    first = AgentRuntime(context).run_turn(
        session_id=session.id,
        user_id="u1",
        text="create skill demo",
        thread_id=session.thread_id,
    )
    assert first["status"] == "awaiting_human"

    second_context = RuntimeContext.from_settings(settings, db)
    resumed = AgentRuntime(second_context).resume_turn(
        session_id=session.id,
        approved=True,
        thread_id=session.thread_id,
    )
    assert resumed["status"] == "finished"
    names = [skill.name for skill in second_context.skill_registry.list_skills(tmp_path)]
    assert "demo-skill" in names
