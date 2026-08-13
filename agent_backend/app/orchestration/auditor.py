"""Real-time sub-agent audit monitor running on a background thread."""

from __future__ import annotations

import queue
import threading
from typing import Any

from agent_backend.app.core.context import RuntimeContext
from agent_backend.app.observability.events import Event

_AUDITED_TYPES = {
    "llm_started",
    "llm_finished",
    "thinking_delta",
    "tool_call_started",
    "tool_call_completed",
    "command_started",
    "command_finished",
    "error",
    "dangerous_command_detected",
}


class AuditMonitor:
    def __init__(self, context: RuntimeContext, parent_session_id: str) -> None:
        self.context = context
        self.parent_session_id = parent_session_id
        self.subscriber = context.event_bus.subscribe()
        self.trace_id: str | None = None
        self.stats: dict[str, dict[str, Any]] = {}
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self, trace_id: str | None) -> None:
        self.trace_id = trace_id
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def finish(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5)
        self._drain_remaining()
        self._publish_summary()
        self.context.event_bus.unsubscribe(self.subscriber)

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                event = self.subscriber.get(timeout=0.2)
            except queue.Empty:
                continue
            if event is None:
                break
            self._handle(event)

    def _drain_remaining(self) -> None:
        while True:
            try:
                event = self.subscriber.get_nowait()
            except queue.Empty:
                return
            if event is not None:
                self._handle(event)

    def _handle(self, event: Event) -> None:
        if not isinstance(event, Event):
            return
        if event.trace_id != self.trace_id:
            return
        if not event.session_id or event.session_id == self.parent_session_id:
            return
        session_id = event.session_id
        stats = self.stats.setdefault(session_id, {"events": 0, "errors": 0, "dangerous": 0})
        stats["events"] += 1
        if event.type == "error":
            stats["errors"] += 1
        if event.type == "dangerous_command_detected":
            stats["dangerous"] += 1
        if event.type in _AUDITED_TYPES:
            self.context.event_bus.publish(
                Event(
                    type="agent_audit_event",
                    session_id=self.parent_session_id,
                    payload={
                        "sub_session_id": session_id,
                        "event_type": event.type,
                        "payload": event.payload,
                    },
                )
            )

    def _publish_summary(self) -> None:
        for session_id, stats in self.stats.items():
            self.context.event_bus.publish(
                Event(
                    type="agent_audit",
                    session_id=self.parent_session_id,
                    payload={
                        "sub_session_id": session_id,
                        "events": stats.get("events", 0),
                        "errors": stats.get("errors", 0),
                        "dangerous": stats.get("dangerous", 0),
                    },
                )
            )
