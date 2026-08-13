"""Cross-session memory consolidation into durable knowledge facts."""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy import select

from agent_backend.app.memory.store import MemoryStore
from agent_backend.app.storage.database import Database
from agent_backend.app.storage.models import MemoryFact as MemoryFactRow
from agent_backend.app.storage.models import Session, SessionSummary


@dataclass
class ConsolidationResult:
    saved: int = 0
    skipped: int = 0
    knowledge: list[str] = field(default_factory=list)


class MemoryConsolidator:
    """Merges running summaries from recent sessions into L3/L4 knowledge facts."""

    def __init__(self, db: Database, store: MemoryStore | None = None) -> None:
        self.db = db
        self.store = store or MemoryStore(db)

    def consolidate(self, user_id: str, window: int = 50) -> ConsolidationResult:
        candidates: list[str] = []
        with self.db.session() as session:
            summaries = session.scalars(
                select(SessionSummary)
                .join(Session, Session.id == SessionSummary.session_id)
                .where(Session.user_id == user_id, Session.status != "deleted")
                .order_by(SessionSummary.updated_at.desc())
                .limit(window)
            )
            for summary in summaries:
                data = summary.summary or {}
                for key in ("goals", "decisions", "key_facts", "progress"):
                    candidates.extend(data.get(key) or [])

        result = ConsolidationResult()
        seen_subjects = self._existing_subjects(user_id)
        for item in candidates:
            text = str(item).strip()
            if not text:
                continue
            subject = text[:64]
            if subject in seen_subjects:
                result.skipped += 1
                continue
            self.store.save_fact(
                user_id=user_id,
                session_id=None,
                subject=subject,
                content=text,
                kind="knowledge",
                scope="user",
                importance=0.6,
                confidence=0.8,
            )
            seen_subjects.add(subject)
            result.saved += 1
            result.knowledge.append(text)
        return result

    def _existing_subjects(self, user_id: str) -> set[str]:
        with self.db.session() as session:
            rows = session.scalars(
                select(MemoryFactRow.subject).where(
                    MemoryFactRow.user_id == user_id,
                    MemoryFactRow.status == "active",
                )
            )
            return set(rows)
