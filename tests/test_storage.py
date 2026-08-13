"""Storage and FTS search tests."""

from __future__ import annotations

from agent_backend.app.storage.database import Database
from agent_backend.app.storage.fts import search_memory_facts
from agent_backend.app.storage.models import MemoryFact, new_id


def test_memory_fact_fts_search(db: Database) -> None:
    with db.transaction() as session:
        session.add(
            MemoryFact(
                id=new_id("mem"),
                user_id="u1",
                subject="python",
                content="user prefers python for backend work",
                tags=["language"],
            )
        )
    with db.session() as session:
        results = search_memory_facts(session, "u1", "python")
    assert len(results) == 1
    assert results[0]["subject"] == "python"


def test_memory_fact_fts_scoped_to_user(db: Database) -> None:
    with db.transaction() as session:
        session.add(
            MemoryFact(
                id=new_id("mem"),
                user_id="u1",
                subject="python",
                content="python preference",
                tags=[],
            )
        )
    with db.session() as session:
        assert search_memory_facts(session, "other", "python") == []
