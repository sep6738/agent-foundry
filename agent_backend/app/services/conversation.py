"""Conversation application service: turns, HITL resume, abort, and compaction."""

from __future__ import annotations

from typing import Any

from agent_backend.app.core.context import RuntimeContext
from agent_backend.app.core.runtime import AgentRuntime
from agent_backend.app.orchestration import TaskOrchestrator


class ConversationService:
    def __init__(self, context: RuntimeContext) -> None:
        self.context = context
        self._runtime: AgentRuntime | None = None

    @property
    def runtime(self) -> AgentRuntime:
        if self._runtime is None:
            self._runtime = AgentRuntime(self.context)
        return self._runtime

    def run_turn(
        self,
        *,
        session_id: str,
        user_id: str,
        text: str,
        thread_id: str,
        trace_id: str | None = None,
    ) -> dict[str, Any]:
        return TaskOrchestrator(self.context).run_task(
            session_id=session_id,
            user_id=user_id,
            text=text,
            thread_id=thread_id,
            trace_id=trace_id,
        )

    def resume_turn(
        self,
        *,
        session_id: str,
        approved: bool,
        thread_id: str,
        trace_id: str | None = None,
    ) -> dict[str, Any]:
        return self.runtime.resume_turn(
            session_id=session_id,
            approved=approved,
            thread_id=thread_id,
            trace_id=trace_id,
        )

    def abort(self, session_id: str) -> bool:
        if self.context.session_manager.get(session_id) is None:
            return False
        self.context.abort_controller.abort(session_id)
        self.context.session_manager.update_status(session_id, "aborted")
        return True

    def compact(self, session_id: str) -> dict[str, Any] | None:
        manager = self.context.session_manager
        if manager.get(session_id) is None:
            return None
        entries = manager.history(session_id)
        messages = [
            {
                "role": entry["payload"].get("role", entry["type"]),
                "content": str(entry["payload"].get("content", "")),
                "id": entry["id"],
            }
            for entry in entries
        ]
        summary = self.context.memory_store.summarize(session_id)
        outcome = self.context.compressor.compress(
            session_id,
            self.context.settings.default_token_budget,
            messages,
            summary,
        )
        return {
            "result": outcome.result.__dict__,
            "context_messages": outcome.context_messages,
        }
