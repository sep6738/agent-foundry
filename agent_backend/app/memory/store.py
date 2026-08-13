"""Memory store: structured facts, versioning, scoring, and summaries."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select

from agent_backend.app.memory.scoring import extract_keywords, score_fact
from agent_backend.app.storage.database import Database
from agent_backend.app.storage.fts import search_memory_facts
from agent_backend.app.storage.models import MemoryFact as MemoryFactRow
from agent_backend.app.storage.models import MemoryFactVersion, SessionSummary, new_id


@dataclass
class MemoryFact:
    id: str
    user_id: str
    session_id: str | None
    kind: str
    subject: str
    content: str
    tags: list[str] = field(default_factory=list)
    keywords: list[str] = field(default_factory=list)
    scope: str = "user"
    importance: float = 0.5
    confidence: float = 0.7
    status: str = "active"
    score: float = 0.0


class MemoryStore:
    """Persists and retrieves long-term facts without vector search."""

    def __init__(self, db: Database) -> None:
        self.db = db

    def save_fact(
        self,
        *,
        user_id: str,
        session_id: str | None,
        subject: str,
        content: str,
        kind: str = "fact",
        tags: list[str] | None = None,
        keywords: list[str] | None = None,
        scope: str = "user",
        importance: float = 0.5,
        confidence: float = 0.7,
        ttl: datetime | None = None,
    ) -> MemoryFact:
        keywords = keywords or extract_keywords(f"{subject} {content}")
        with self.db.transaction() as session:
            existing = (
                session.execute(
                    select(MemoryFactRow).where(
                        MemoryFactRow.user_id == user_id,
                        MemoryFactRow.subject == subject,
                        MemoryFactRow.status == "active",
                        MemoryFactRow.scope == scope,
                    )
                )
                .scalars()
                .first()
            )
            fact_id = new_id("mem")
            status = "active"
            if existing is not None and existing.content != content:
                if existing.confidence >= 0.8 and confidence >= 0.8:
                    status = "needs_review"
                else:
                    self._version_row(session, existing)
                    existing.status = "superseded"
                    existing.superseded_by = fact_id
            row = MemoryFactRow(
                id=fact_id,
                user_id=user_id,
                session_id=session_id,
                kind=kind,
                subject=subject,
                content=content,
                tags=tags or [],
                keywords=keywords,
                scope=scope,
                importance=importance,
                confidence=confidence,
                status=status,
                ttl=ttl,
            )
            session.add(row)
            session.flush()
            return self._to_dataclass(row)

    def search(self, user_id: str, query: str, limit: int = 10) -> list[MemoryFact]:
        with self.db.session() as session:
            rows = search_memory_facts(session, user_id, query, limit=max(limit * 3, 30))
            facts: list[MemoryFact] = []
            hit_ids = [row["id"] for row in rows]
            if hit_ids:
                session.execute(
                    MemoryFactRow.__table__.update()
                    .where(MemoryFactRow.id.in_(hit_ids))
                    .values(last_access_at=datetime.now(UTC))
                )
                session.commit()
            for row in rows:
                tags = row.get("tags") or []
                if isinstance(tags, str):
                    tags = _json_list(tags)
                keywords = row.get("keywords") or []
                if isinstance(keywords, str):
                    keywords = _json_list(keywords)
                last_access = row.get("last_access_at")
                if isinstance(last_access, str):
                    try:
                        last_access = datetime.fromisoformat(last_access)
                    except ValueError:
                        last_access = None
                row["last_access_at"] = last_access
                score = score_fact(row, query)
                facts.append(
                    MemoryFact(
                        id=row_id(row),
                        user_id=user_id,
                        session_id=None,
                        kind=row.get("kind") or "fact",
                        subject=row.get("subject") or "",
                        content=row.get("content") or "",
                        tags=tags,
                        keywords=keywords,
                        scope=row.get("scope") or "user",
                        importance=float(row.get("importance") or 0.5),
                        confidence=float(row.get("confidence") or 0.7),
                        status="active",
                        score=score,
                    )
                )
            facts.sort(key=lambda fact: (fact.score, fact.importance), reverse=True)
            return facts[:limit]

    def get(self, memory_id: str) -> MemoryFact | None:
        with self.db.session() as session:
            row = session.get(MemoryFactRow, memory_id)
            return self._to_dataclass(row) if row else None

    def update_fact(self, memory_id: str, content: str) -> MemoryFact | None:
        with self.db.transaction() as session:
            old = session.get(MemoryFactRow, memory_id)
            if old is None:
                return None
            self._version_row(session, old)
            new_row = MemoryFactRow(
                id=new_id("mem"),
                user_id=old.user_id,
                session_id=old.session_id,
                kind=old.kind,
                subject=old.subject,
                content=content,
                tags=list(old.tags or []),
                keywords=list(old.keywords or []),
                scope=old.scope,
                importance=old.importance,
                confidence=old.confidence,
                status="active",
            )
            old.superseded_by = new_row.id
            old.status = "superseded"
            session.add(new_row)
            session.flush()
            return self._to_dataclass(new_row)

    def confirm_fact(self, memory_id: str) -> MemoryFact | None:
        with self.db.transaction() as session:
            row = session.get(MemoryFactRow, memory_id)
            if row is None:
                return None
            if row.status != "needs_review":
                return self._to_dataclass(row)
            older = (
                session.execute(
                    select(MemoryFactRow).where(
                        MemoryFactRow.user_id == row.user_id,
                        MemoryFactRow.subject == row.subject,
                        MemoryFactRow.scope == row.scope,
                        MemoryFactRow.status == "active",
                        MemoryFactRow.id != row.id,
                    )
                )
                .scalars()
                .first()
            )
            if older is not None:
                self._version_row(session, older)
                older.status = "superseded"
                older.superseded_by = row.id
            row.status = "active"
            session.flush()
            return self._to_dataclass(row)

    def forget(self, memory_id: str) -> bool:
        with self.db.transaction() as session:
            row = session.get(MemoryFactRow, memory_id)
            if row is None:
                return False
            row.status = "forgotten"
            return True

    def update_running_summary(self, session_id: str, text: str) -> None:
        """Legacy helper kept for API compatibility."""
        from agent_backend.app.memory.summarizer import MemorySummarizer

        MemorySummarizer(self.db).update(session_id, user_text=text, response_text="")

    def summarize(self, session_id: str) -> dict[str, Any]:
        with self.db.session() as session:
            summary = (
                session.execute(
                    select(SessionSummary)
                    .where(SessionSummary.session_id == session_id)
                    .order_by(SessionSummary.updated_at.desc())
                )
                .scalars()
                .first()
            )
            return dict(summary.summary) if summary else {}

    @staticmethod
    def _version_row(session, row: MemoryFactRow) -> MemoryFactVersion:
        current = session.scalar(
            select(func.max(MemoryFactVersion.version)).where(MemoryFactVersion.fact_id == row.id)
        )
        version = int(current or 0) + 1
        version_row = MemoryFactVersion(
            id=new_id("ver"),
            fact_id=row.id,
            version=version,
            content=row.content,
            payload={
                "tags": row.tags,
                "keywords": row.keywords,
                "importance": row.importance,
                "confidence": row.confidence,
            },
        )
        session.add(version_row)
        return version_row

    @staticmethod
    def _to_dataclass(row: MemoryFactRow) -> MemoryFact:
        return MemoryFact(
            id=row.id,
            user_id=row.user_id,
            session_id=row.session_id,
            kind=row.kind,
            subject=row.subject,
            content=row.content,
            tags=list(row.tags or []),
            keywords=list(row.keywords or []),
            scope=row.scope,
            importance=row.importance,
            confidence=row.confidence,
            status=row.status,
        )


def row_id(row: dict[str, Any]) -> str:
    return str(row.get("id") or "")


def _json_list(value: Any) -> list[str]:
    import json

    try:
        parsed = json.loads(value)
        return list(parsed) if isinstance(parsed, list) else []
    except (TypeError, json.JSONDecodeError):
        return []
