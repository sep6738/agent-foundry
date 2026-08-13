"""Session application service used by the HTTP layer."""

from __future__ import annotations

import uuid
from typing import Any

from agent_backend.app.core.context import RuntimeContext
from agent_backend.app.observability.events import Event
from agent_backend.app.sessions.repository import SessionRepository


class SessionService:
    def __init__(self, context: RuntimeContext) -> None:
        self.context = context
        self.repository = SessionRepository(context.session_manager)

    def create(
        self,
        user_id: str,
        title: str = "Untitled",
        project_id: str | None = None,
    ) -> dict[str, Any]:
        session = self.repository.create(user_id, title, project_id=project_id)
        self.context.event_bus.publish(
            Event(
                type="session_started",
                session_id=session.id,
                payload={"user_id": session.user_id, "title": session.title},
            )
        )
        return {
            "id": session.id,
            "user_id": session.user_id,
            "thread_id": session.thread_id,
            "title": session.title,
            "status": session.status,
            "project_id": session.project_id,
        }

    def list(self, user_id: str | None = None) -> list[dict[str, Any]]:
        return [
            {
                "id": session.id,
                "user_id": session.user_id,
                "thread_id": session.thread_id,
                "title": session.title,
                "status": session.status,
                "project_id": session.project_id,
                "created_at": session.created_at.isoformat(),
            }
            for session in self.repository.list(user_id)
        ]

    def get(self, session_id: str) -> dict[str, Any] | None:
        session = self.repository.get(session_id)
        if session is None or session.status == "deleted":
            return None
        return {
            "id": session.id,
            "user_id": session.user_id,
            "thread_id": session.thread_id,
            "title": session.title,
            "status": session.status,
            "project_id": session.project_id,
            "created_at": session.created_at.isoformat(),
            "updated_at": session.updated_at.isoformat(),
        }

    def delete(self, session_id: str) -> bool:
        if self.repository.get(session_id) is None:
            return False
        self.context.abort_controller.abort(session_id)
        self.repository.update_status(session_id, "deleted")
        self.context.event_bus.publish(
            Event(
                type="session_finished",
                session_id=session_id,
                payload={"status": "deleted"},
            )
        )
        return True

    def history(self, session_id: str) -> list[dict[str, Any]]:
        return self.repository.history(session_id)

    def events(self, session_id: str) -> list[dict[str, Any]]:
        return self.repository.events(session_id)

    def get_instructions(self, session_id: str) -> list[dict[str, Any]]:
        return self.repository.get_instructions(session_id)

    def inject_instruction(
        self,
        session_id: str,
        content: str,
        key: str | None = None,
    ) -> dict[str, Any]:
        key = key or f"inst_{uuid.uuid4().hex[:12]}"
        self.context.session_manager.append_entry(
            session_id,
            "session_instruction",
            {"key": key, "content": content},
        )
        self.context.event_bus.publish(
            Event(
                type="instruction_loaded",
                session_id=session_id,
                payload={"session_instruction": key},
            )
        )
        return {"session_id": session_id, "key": key, "injected": True}

    def remove_instruction(self, session_id: str, key: str) -> bool:
        return self.context.session_manager.remove_session_instruction(session_id, key)
