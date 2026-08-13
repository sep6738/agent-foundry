"""Subagent and multi-agent orchestration tests."""

from __future__ import annotations

import queue
from pathlib import Path

from agent_backend.app.config import Settings
from agent_backend.app.core.context import RuntimeContext
from agent_backend.app.orchestration import TaskOrchestrator
from agent_backend.app.orchestration.classifier import ComplexityClassifier
from agent_backend.app.orchestration.models import TaskComplexity, TaskStep
from agent_backend.app.orchestration.planner import RequirementAnalyzer
from agent_backend.app.orchestration.recruiter import SkillRecruiter
from agent_backend.app.skills.registry import SkillRegistry
from agent_backend.app.storage.database import Database


def _drain(subscriber: queue.Queue):
    events = []
    while True:
        try:
            event = subscriber.get_nowait()
        except queue.Empty:
            return events
        if event is not None:
            events.append(event)


def test_classifier_selects_complexity_levels() -> None:
    classifier = ComplexityClassifier()
    assert classifier.classify("hello") == TaskComplexity.SIMPLE
    assert classifier.classify("异步并行处理两个任务") == TaskComplexity.ASYNC
    assert classifier.classify("复杂系统需要拆解多模块") == TaskComplexity.COMPLEX


def test_analyzer_decomposes_complex_task_and_marks_async() -> None:
    steps = RequirementAnalyzer().analyze("复杂系统。并行处理模块A。后台执行模块B。")
    assert len(steps) == 3
    assert any(step.dispatch == "async" for step in steps)


def test_hr_recruiter_maps_skill_to_employee(db: Database, tmp_path: Path) -> None:
    registry = SkillRegistry(db, (".agent/skills",))
    content = (
        "---\nname: code-review\ndescription: Review code for bugs\n"
        "when: 用户要求审查代码\n---\n\n## Steps\n1. Read files.\n"
    )
    registry.save("code-review", content, tmp_path)
    recruiter = SkillRecruiter(registry)
    steps = [TaskStep(id="s0", title="审查代码", description="请做代码审查", dispatch="sync")]
    agents = recruiter.recruit(steps, tmp_path)
    assert agents[0].name == "employee-0"
    assert "code-review" in agents[0].skills


def test_orchestrator_simple_task_uses_single_agent(settings: Settings, db: Database) -> None:
    context = RuntimeContext.from_settings(settings, db)
    session = context.session_manager.create("u1", "simple")
    result = TaskOrchestrator(context).run_task(
        session_id=session.id,
        user_id="u1",
        text="hello",
        thread_id=session.thread_id,
    )
    assert result["status"] == "finished"
    assert result.get("mode") is None


def test_orchestrator_complex_task_spawns_and_audits_agents(
    settings: Settings, db: Database
) -> None:
    context = RuntimeContext.from_settings(settings, db)
    session = context.session_manager.create("u1", "complex")
    subscriber = context.event_bus.subscribe()
    result = TaskOrchestrator(context).run_task(
        session_id=session.id,
        user_id="u1",
        text="复杂系统。并行处理模块A。后台执行模块B。",
        thread_id=session.thread_id,
    )
    events = _drain(subscriber)
    context.event_bus.unsubscribe(subscriber)
    event_types = {event.type for event in events}
    assert result["status"] == "finished"
    assert result["mode"] == "complex"
    assert "task_classified" in event_types
    assert "task_plan_created" in event_types
    assert "agent_audit" in event_types
    assert len(context.session_manager.list("u1")) > 1
