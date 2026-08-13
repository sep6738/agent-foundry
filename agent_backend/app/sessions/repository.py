"""Data-access repository over the session manager."""

from __future__ import annotations

from typing import Any

from agent_backend.app.sessions.manager import SessionManager
from agent_backend.app.storage.models import Session


class SessionRepository:
    def __init__(self, manager: SessionManager) -> None:
        self.manager = manager

    def create(
        self,
        user_id: str,
        title: str = "Untitled",
        project_id: str | None = None,
    ) -> Session:
        return self.manager.create(user_id, title, project_id=project_id)

    def get(self, session_id: str) -> Session | None:
        return self.manager.get(session_id)

    def list(self, user_id: str | None = None) -> list[Session]:
        return self.manager.list(user_id)

    def history(self, session_id: str) -> list[dict[str, Any]]:
        return self.manager.history(session_id)

    def events(self, session_id: str) -> list[dict[str, Any]]:
        return self.manager.events(session_id)

    def get_instructions(self, session_id: str) -> list[dict[str, Any]]:
        return self.manager.get_session_instructions(session_id)

    def update_status(self, session_id: str, status: str) -> Session | None:
        return self.manager.update_status(session_id, status)
