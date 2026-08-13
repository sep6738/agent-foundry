"""Session lifecycle, entry logging, instructions, and tool-call records."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select

from agent_backend.app.storage.database import Database
from agent_backend.app.storage.models import Event, Session, SessionEntry, ToolCall, User, new_id


class SessionManager:
    def __init__(self, db: Database) -> None:
        self.db = db

    def create(
        self,
        user_id: str,
        title: str = "Untitled",
        project_id: str | None = None,
    ) -> Session:
        with self.db.transaction() as session:
            user = session.execute(select(User).where(User.id == user_id)).scalars().first()
            if user is None:
                user = User(id=user_id, name=user_id)
                session.add(user)
            row = Session(
                id=new_id("sess"),
                user_id=user_id,
                thread_id=f"thread_{uuid.uuid4().hex[:12]}",
                title=title or "Untitled",
                project_id=project_id,
            )
            session.add(row)
            session.flush()
            return row

    def list(self, user_id: str | None = None) -> list[Session]:
        with self.db.session() as session:
            query = select(Session).order_by(Session.updated_at.desc())
            if user_id:
                query = query.where(Session.user_id == user_id)
            return list(session.scalars(query))

    def get(self, session_id: str) -> Session | None:
        with self.db.session() as session:
            return session.get(Session, session_id)

    def update_status(self, session_id: str, status: str) -> Session | None:
        with self.db.transaction() as session:
            row = session.get(Session, session_id)
            if row is None:
                return None
            row.status = status
            return row

    def append_entry(self, session_id: str, entry_type: str, payload: dict[str, Any]) -> str:
        with self.db.transaction() as session:
            entry = SessionEntry(
                id=new_id("ent"),
                session_id=session_id,
                type=entry_type,
                payload=payload,
            )
            session.add(entry)
            session.flush()
            return entry.id

    def get_session_instructions(self, session_id: str) -> list[dict[str, Any]]:
        """Return active session-level instructions (injections minus removals)."""
        with self.db.session() as session:
            rows = session.execute(
                select(SessionEntry)
                .where(
                    SessionEntry.session_id == session_id,
                    SessionEntry.type.in_(["session_instruction", "session_instruction_removed"]),
                )
                .order_by(SessionEntry.ts)
            ).scalars()
            removed: set[str] = set()
            active: list[dict[str, Any]] = []
            for row in rows:
                payload = row.payload or {}
                key = str(payload.get("key", ""))
                if row.type == "session_instruction_removed":
                    removed.add(key)
                    continue
                if key and key not in removed:
                    active.append(
                        {
                            "key": key,
                            "content": str(payload.get("content", "")),
                            "ts": row.ts.isoformat(),
                        }
                    )
            return [item for item in active if item["key"] not in removed]

    def remove_session_instruction(self, session_id: str, key: str) -> bool:
        active = self.get_session_instructions(session_id)
        if not any(item["key"] == key for item in active):
            return False
        return self.append_entry(
            session_id,
            "session_instruction_removed",
            {"key": key},
        )

    def enqueue_follow_up(self, session_id: str, content: str) -> str:
        return self.append_entry(
            session_id,
            "follow_up",
            {"content": content, "done": False},
        )

    def pending_follow_ups(self, session_id: str) -> list[dict[str, Any]]:
        with self.db.session() as session:
            rows = session.execute(
                select(SessionEntry)
                .where(
                    SessionEntry.session_id == session_id,
                    SessionEntry.type == "follow_up",
                )
                .order_by(SessionEntry.ts)
            ).scalars()
            return [
                {"id": row.id, "content": (row.payload or {}).get("content", "")}
                for row in rows
                if not (row.payload or {}).get("done")
            ]

    def mark_follow_up_done(self, entry_id: str) -> bool:
        with self.db.transaction() as session:
            row = session.get(SessionEntry, entry_id)
            if row is None:
                return False
            payload = dict(row.payload or {})
            payload["done"] = True
            row.payload = payload
            return True

    def record_tool_call(
        self,
        session_id: str,
        tool_name: str,
        args: dict[str, Any],
        result: dict[str, Any],
        status: int,
    ) -> None:
        with self.db.transaction() as session:
            session.add(
                ToolCall(
                    id=new_id("tc"),
                    session_id=session_id,
                    tool_name=tool_name,
                    args=args,
                    result=result,
                    status=status,
                )
            )

    def history(self, session_id: str) -> list[dict[str, Any]]:
        with self.db.session() as session:
            rows = session.execute(
                select(SessionEntry)
                .where(SessionEntry.session_id == session_id)
                .order_by(SessionEntry.ts)
            ).scalars()
            return [
                {"id": row.id, "type": row.type, "payload": row.payload, "ts": row.ts.isoformat()}
                for row in rows
            ]

    def events(self, session_id: str) -> list[dict[str, Any]]:
        with self.db.session() as session:
            rows = session.execute(
                select(Event).where(Event.session_id == session_id).order_by(Event.ts)
            ).scalars()
            return [
                {
                    "id": row.id,
                    "type": row.type,
                    "payload": row.payload,
                    "ts": row.ts.isoformat(),
                }
                for row in rows
            ]
