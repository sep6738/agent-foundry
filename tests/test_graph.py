"""Agent graph and runtime tests."""

from __future__ import annotations

import queue
from pathlib import Path

from agent_backend.app.config import Settings
from agent_backend.app.core.context import RuntimeContext
from agent_backend.app.core.runtime import AgentRuntime
from agent_backend.app.storage.database import Database


def test_runtime_tool_turn(settings: Settings, db: Database) -> None:
    context = RuntimeContext.from_settings(settings, db)
    manager = context.session_manager
    session = manager.create("u1", "test")
    runtime = AgentRuntime(context)
    result = runtime.run_turn(
        session_id=session.id,
        user_id="u1",
        text="list directory",
        thread_id=session.thread_id,
    )
    assert result["response"]
    history = manager.history(session.id)
    assert any(entry["type"] == "user_message" for entry in history)
    assert any(entry["type"] == "assistant_message" for entry in history)


def test_multi_turn_persists_across_runtime_instances(settings: Settings, db: Database) -> None:
    context = RuntimeContext.from_settings(settings, db)
    manager = context.session_manager
    session = manager.create("u1", "multi")
    first = AgentRuntime(context).run_turn(
        session_id=session.id,
        user_id="u1",
        text="list directory",
        thread_id=session.thread_id,
    )
    assert first["status"] == "finished"
    second = AgentRuntime(context).run_turn(
        session_id=session.id,
        user_id="u1",
        text="read AGENTS.md",
        thread_id=session.thread_id,
    )
    assert second["status"] == "finished"
    assert "Repository Guidelines" in second["response"]
    history = manager.history(session.id)
    assert sum(entry["type"] == "tool_result" for entry in history) == 2


def test_human_approval_interrupt_and_resume(tmp_path: Path) -> None:
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
    manager = context.session_manager
    session = manager.create("u1", "hitl")
    runtime = AgentRuntime(context)
    first = runtime.run_turn(
        session_id=session.id,
        user_id="u1",
        text="create skill demo",
        thread_id=session.thread_id,
    )
    assert first["status"] == "awaiting_human"
    assert first["human_request"]["tool"] == "edit_skill"
    assert first["human_request"]["purpose"]
    assert manager.get(session.id).status == "awaiting_human"
    resumed = runtime.resume_turn(
        session_id=session.id,
        approved=True,
        thread_id=session.thread_id,
    )
    assert resumed["status"] == "finished"
    names = [skill.name for skill in context.skill_registry.list_skills(tmp_path)]
    assert "demo-skill" in names


def test_memory_recall_across_turns(settings: Settings, db: Database) -> None:
    context = RuntimeContext.from_settings(settings, db)
    session = context.session_manager.create("u1", "memory")
    runtime = AgentRuntime(context)
    first = runtime.run_turn(
        session_id=session.id,
        user_id="u1",
        text="记住我偏好 Python 语言",
        thread_id=session.thread_id,
    )
    assert first["status"] == "finished"
    second = runtime.run_turn(
        session_id=session.id,
        user_id="u1",
        text="Python 语言偏好是什么？",
        thread_id=session.thread_id,
    )
    assert "python" in second["response"].lower() or "Python" in second["response"]


def test_runtime_emits_streaming_events(settings: Settings, db: Database) -> None:
    context = RuntimeContext.from_settings(settings, db)
    session = context.session_manager.create("u1", "stream")
    subscriber = context.event_bus.subscribe()
    AgentRuntime(context).run_turn(
        session_id=session.id,
        user_id="u1",
        text="list directory",
        thread_id=session.thread_id,
    )
    event_types = []
    while True:
        try:
            event = subscriber.get_nowait()
        except queue.Empty:
            break
        if event is not None:
            event_types.append(event.type)
    context.event_bus.unsubscribe(subscriber)
    assert "llm_started" in event_types
    assert "llm_finished" in event_types
    assert "tool_call_started" in event_types
    assert "message_delta" in event_types
