"""AgentRuntime: turn execution and HITL resume around the LangGraph graph."""

from __future__ import annotations

from typing import Any

from langgraph.errors import GraphInterrupt
from langgraph.types import Command

from agent_backend.app.core.context import AgentAborted, RuntimeContext
from agent_backend.app.core.state import AgentMessage
from agent_backend.app.observability.events import Event
from agent_backend.app.observability.trace import reset_trace_id, set_trace_id


class AgentRuntime:
    def __init__(self, context: RuntimeContext) -> None:
        self.context = context
        self.graph = context.get_graph()

    def run_turn(
        self,
        *,
        session_id: str,
        user_id: str,
        text: str,
        thread_id: str,
        trace_id: str | None = None,
    ) -> dict[str, Any]:
        context = self.context
        trace_token = set_trace_id(trace_id)
        session = context.session_manager.get(session_id)
        if session is None:
            reset_trace_id(trace_token)
            return {"error": "session not found"}
        if session.status == "awaiting_human":
            reset_trace_id(trace_token)
            return {"error": "session is waiting for human approval"}

        context.abort_controller.clear(session_id)
        context.event_bus.publish(
            Event(type="turn_started", session_id=session_id, payload={"turn_id": session_id})
        )
        try:
            project_root = context.project_manager.resolve_path(
                session.project_id,
                context.settings.project_root,
            )
        except ValueError as exc:
            reset_trace_id(trace_token)
            return {"error": str(exc)}
        entry_id = context.session_manager.append_entry(
            session_id,
            "user_message",
            {"content": text, "role": "user"},
        )
        initial: dict[str, Any] = {
            "session_id": session_id,
            "user_id": user_id,
            "project_root": str(project_root),
            "current_query": text,
            "messages": [AgentMessage(role="user", content=text, message_id=entry_id)],
            "tool_results": [],
            "tool_rounds": 0,
            "flags": {},
        }
        config = {"configurable": {"thread_id": thread_id}}
        try:
            result = self.graph.invoke(initial, config=config)
        except GraphInterrupt as exc:
            interrupts = exc.args[0] if exc.args else ()
            outcome = self._handle_interrupt(session_id, interrupts)
            reset_trace_id(trace_token)
            return outcome
        except AgentAborted:
            context.session_manager.update_status(session_id, "aborted")
            context.event_bus.publish(
                Event(type="error", session_id=session_id, payload={"error": "aborted"})
            )
            context.abort_controller.clear(session_id)
            reset_trace_id(trace_token)
            return {"status": "aborted", "session_id": session_id}
        interrupts = result.get("__interrupt__") if isinstance(result, dict) else None
        if interrupts:
            outcome = self._handle_interrupt(session_id, interrupts)
            reset_trace_id(trace_token)
            return outcome
        self._finish_turn(session_id, user_id, result, text)
        reset_trace_id(trace_token)
        return {
            "session_id": session_id,
            "response": result.get("response", ""),
            "status": "finished",
        }

    def resume_turn(
        self,
        *,
        session_id: str,
        approved: bool,
        thread_id: str,
        trace_id: str | None = None,
    ) -> dict[str, Any]:
        context = self.context
        trace_token = set_trace_id(trace_id)
        session = context.session_manager.get(session_id)
        if session is None:
            reset_trace_id(trace_token)
            return {"error": "session not found"}
        if session.status != "awaiting_human":
            reset_trace_id(trace_token)
            return {"error": "session is not waiting for human approval"}

        context.event_bus.publish(
            Event(
                type="human_resolved",
                session_id=session_id,
                payload={"approved": approved},
            )
        )
        context.session_manager.append_entry(
            session_id,
            "human_resolution",
            {"approved": approved},
        )
        config = {"configurable": {"thread_id": thread_id}}
        try:
            result = self.graph.invoke(Command(resume={"approved": approved}), config=config)
        except GraphInterrupt as exc:
            interrupts = exc.args[0] if exc.args else ()
            outcome = self._handle_interrupt(session_id, interrupts)
            reset_trace_id(trace_token)
            return outcome
        except AgentAborted:
            context.session_manager.update_status(session_id, "aborted")
            context.event_bus.publish(
                Event(type="error", session_id=session_id, payload={"error": "aborted"})
            )
            context.abort_controller.clear(session_id)
            reset_trace_id(trace_token)
            return {"status": "aborted", "session_id": session_id}
        interrupts = result.get("__interrupt__") if isinstance(result, dict) else None
        if interrupts:
            outcome = self._handle_interrupt(session_id, interrupts)
            reset_trace_id(trace_token)
            return outcome
        self._finish_turn(session_id, session.user_id, result, "")
        reset_trace_id(trace_token)
        return {
            "session_id": session_id,
            "response": result.get("response", ""),
            "status": "finished",
        }

    def _handle_interrupt(
        self,
        session_id: str,
        interrupts: list | tuple,
    ) -> dict[str, Any]:
        payload = interrupts[-1].value if interrupts else {}
        self.context.session_manager.append_entry(
            session_id,
            "human_request",
            payload,
        )
        self.context.session_manager.update_status(session_id, "awaiting_human")
        self.context.event_bus.publish(
            Event(
                type="human_requested",
                session_id=session_id,
                payload=payload if isinstance(payload, dict) else {"value": payload},
            )
        )
        return {"status": "awaiting_human", "human_request": payload}

    def _finish_turn(
        self,
        session_id: str,
        user_id: str,
        result: dict[str, Any],
        query: str,
    ) -> None:
        context = self.context
        response = result.get("response", "")
        entry_id = context.session_manager.append_entry(
            session_id,
            "assistant_message",
            {"content": response, "role": "assistant"},
        )
        context.usage_recorder.record(session_id, input_text=query, output_text=response)
        context.event_bus.publish(
            Event(
                type="turn_finished",
                session_id=session_id,
                payload={
                    "response": response[:500],
                    "entry_id": entry_id,
                    "user_id": user_id,
                },
            )
        )
        context.session_manager.update_status(session_id, "active")
        context.abort_controller.clear(session_id)
