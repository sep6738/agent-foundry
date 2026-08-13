"""Application service layer tests."""

from __future__ import annotations

import queue

from agent_backend.app.config import Settings
from agent_backend.app.core.context import RuntimeContext
from agent_backend.app.services import ConversationService, SessionService
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


def test_session_service_publishes_lifecycle_events(settings: Settings, db: Database) -> None:
    context = RuntimeContext.from_settings(settings, db)
    service = SessionService(context)
    subscriber = context.event_bus.subscribe()
    created = service.create("u1", "service")
    events = _drain(subscriber)
    context.event_bus.unsubscribe(subscriber)
    assert created["id"]
    assert any(event.type == "session_started" for event in events)
    assert service.delete(created["id"])
    assert service.get(created["id"]) is None


def test_conversation_service_runs_and_compacts(settings: Settings, db: Database) -> None:
    context = RuntimeContext.from_settings(settings, db)
    session = context.session_manager.create("u1", "conv")
    conversation = ConversationService(context)
    result = conversation.run_turn(
        session_id=session.id,
        user_id="u1",
        text="hello",
        thread_id=session.thread_id,
        trace_id="trace-1",
    )
    assert result["status"] == "finished"
    compact = conversation.compact(session.id)
    assert compact is not None
    assert "result" in compact
