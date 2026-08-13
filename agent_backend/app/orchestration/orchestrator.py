"""Task orchestrator: routes simple tasks or multi-agent workflows."""

from __future__ import annotations

from typing import Any

from agent_backend.app.core.context import RuntimeContext
from agent_backend.app.core.runtime import AgentRuntime
from agent_backend.app.observability.events import Event
from agent_backend.app.orchestration.auditor import AuditMonitor
from agent_backend.app.orchestration.classifier import ComplexityClassifier
from agent_backend.app.orchestration.executor import SubAgentExecutor
from agent_backend.app.orchestration.llm_roles import LLMPlanner, LLMRecruiter, LLMScheduler
from agent_backend.app.orchestration.models import TaskComplexity, TaskPlan


class TaskOrchestrator:
    def __init__(self, context: RuntimeContext) -> None:
        self.context = context
        self.classifier = ComplexityClassifier()

    def run_task(
        self,
        *,
        session_id: str,
        user_id: str,
        text: str,
        thread_id: str,
        trace_id: str | None = None,
    ) -> dict[str, Any]:
        session = self.context.session_manager.get(session_id)
        if session is None:
            return {"error": "session not found"}

        kind = self.classifier.classify(text)
        self.context.event_bus.publish(
            Event(
                type="task_classified",
                session_id=session_id,
                payload={"mode": kind.value, "input": text[:200]},
            )
        )
        if kind == TaskComplexity.SIMPLE:
            return AgentRuntime(self.context).run_turn(
                session_id=session_id,
                user_id=user_id,
                text=text,
                thread_id=thread_id,
                trace_id=trace_id,
            )

        context = self.context
        context.event_bus.publish(
            Event(type="turn_started", session_id=session_id, payload={"turn_id": session_id})
        )
        context.session_manager.append_entry(
            session_id, "user_message", {"content": text, "role": "user"}
        )
        steps = LLMPlanner(context).plan(text, kind)
        steps = LLMScheduler(context).schedule(steps, kind)
        agents = LLMRecruiter(context).recruit(
            steps,
            context.settings.project_root,
            user_home=context.user_home,
        )
        plan = TaskPlan(kind=kind, steps=steps, agents=agents)
        context.event_bus.publish(
            Event(
                type="task_plan_created",
                session_id=session_id,
                payload={
                    "mode": kind.value,
                    "steps": [step.title for step in steps],
                    "agents": [agent.name for agent in agents],
                },
            )
        )

        monitor = AuditMonitor(context, session_id)
        monitor.start(trace_id)
        try:
            results = SubAgentExecutor(context, trace_id=trace_id).execute(plan, session, user_id)
        finally:
            monitor.finish()

        response = _render_results(plan, results)
        entry_id = context.session_manager.append_entry(
            session_id,
            "assistant_message",
            {"content": response, "role": "assistant"},
        )
        context.usage_recorder.record(session_id, input_text=text, output_text=response)
        context.event_bus.publish(
            Event(
                type="turn_finished",
                session_id=session_id,
                payload={
                    "response": response[:500],
                    "entry_id": entry_id,
                    "user_id": user_id,
                    "mode": kind.value,
                },
            )
        )
        context.session_manager.update_status(session_id, "active")
        return {
            "session_id": session_id,
            "response": response,
            "status": "finished",
            "mode": kind.value,
        }


def _render_results(plan: TaskPlan, results) -> str:
    lines = [f"任务模式：{plan.kind.value}"]
    for result in results:
        status = "完成" if result.ok else "失败"
        lines.append(f"- {status} [{result.agent_name}] {result.response or result.error or ''}")
    return "\n".join(lines).strip()
