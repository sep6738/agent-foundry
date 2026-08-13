"""Keyword search over SQLite FTS5 virtual tables with a LIKE fallback."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import text
from sqlalchemy.orm import Session


def search_memory_facts(
    session: Session,
    user_id: str,
    query: str,
    limit: int = 20,
) -> list[dict]:
    if not query.strip():
        return []
    now = datetime.now(UTC).isoformat()
    try:
        rows = session.execute(
            text(
                """
                SELECT f.id, f.subject, f.content, f.kind, f.scope, f.importance,
                       f.confidence, f.tags, f.keywords, f.last_access_at, f.ttl,
                       -bm25(memory_facts_fts) AS rank
                FROM memory_facts f
                JOIN memory_facts_fts ON memory_facts_fts.id = f.id
                WHERE memory_facts_fts MATCH :q
                  AND f.user_id = :user_id
                  AND f.status = 'active'
                  AND (f.ttl IS NULL OR f.ttl > :now)
                ORDER BY rank DESC
                LIMIT :limit
                """
            ),
            {"q": query, "user_id": user_id, "limit": limit, "now": now},
        ).mappings()
    except Exception:
        rows = session.execute(
            text(
                """
                SELECT f.id, f.subject, f.content, f.kind, f.scope, f.importance,
                       f.confidence, f.tags, f.keywords, f.last_access_at, f.ttl,
                       0.0 AS rank
                FROM memory_facts f
                WHERE f.user_id = :user_id
                  AND f.status = 'active'
                  AND (f.ttl IS NULL OR f.ttl > :now)
                  AND (f.subject LIKE :like OR f.content LIKE :like OR f.tags LIKE :like)
                ORDER BY f.last_access_at DESC
                LIMIT :limit
                """
            ),
            {
                "like": f"%{query}%",
                "user_id": user_id,
                "limit": limit,
                "now": now,
            },
        ).mappings()
    return [dict(row) for row in rows]


def search_skills(
    session: Session,
    query: str,
    limit: int = 20,
) -> list[dict]:
    if not query.strip():
        return []
    try:
        rows = session.execute(
            text(
                """
                SELECT s.id, s.name, s.description, s.scope, 0.0 AS rank
                FROM skills s
                JOIN skills_fts ON skills_fts.id = s.id
                WHERE skills_fts MATCH :q AND s.status = 'active'
                ORDER BY s.updated_at DESC
                LIMIT :limit
                """
            ),
            {"q": query, "limit": limit},
        ).mappings()
    except Exception:
        rows = session.execute(
            text(
                """
                SELECT s.id, s.name, s.description, s.scope, 0.0 AS rank
                FROM skills s
                WHERE s.status = 'active'
                  AND (s.name LIKE :like OR s.description LIKE :like)
                ORDER BY s.updated_at DESC
                LIMIT :limit
                """
            ),
            {"like": f"%{query}%", "limit": limit},
        ).mappings()
    return [dict(row) for row in rows]
