"""Memory store tests."""

from __future__ import annotations

from agent_backend.app.memory.compressor import MemoryCompressor
from agent_backend.app.memory.consolidator import MemoryConsolidator
from agent_backend.app.memory.retriever import MemoryRetriever
from agent_backend.app.memory.store import MemoryStore
from agent_backend.app.memory.summarizer import MemorySummarizer
from agent_backend.app.sessions.manager import SessionManager
from agent_backend.app.storage.database import Database


def test_save_and_search_fact(db: Database) -> None:
    store = MemoryStore(db)
    store.save_fact(
        user_id="u1",
        session_id=None,
        subject="pytest",
        content="项目测试命令为 pytest tests/",
        tags=["testing"],
    )
    facts = store.search("u1", "pytest")
    assert len(facts) == 1
    assert facts[0].subject == "pytest"


def test_update_versions_and_forget(db: Database) -> None:
    store = MemoryStore(db)
    fact = store.save_fact(
        user_id="u1",
        session_id=None,
        subject="theme",
        content="light",
        tags=["ui"],
    )
    updated = store.update_fact(fact.id, "dark")
    assert updated is not None
    assert updated.content == "dark"
    assert store.get(fact.id).status == "superseded"  # type: ignore[union-attr]
    assert store.forget(updated.id)


def test_scoring_ranks_subject_match_and_importance(db: Database) -> None:
    store = MemoryStore(db)
    store.save_fact(
        user_id="u1",
        session_id=None,
        subject="vim",
        content="prefers vim",
        tags=["editor"],
    )
    store.save_fact(
        user_id="u1",
        session_id=None,
        subject="editor-theme",
        content="dark theme",
        tags=["editor", "vim"],
    )
    facts = store.search("u1", "vim")
    assert facts[0].subject == "vim"
    assert facts[0].score > facts[1].score


def test_conflict_needs_review_then_confirm(db: Database) -> None:
    store = MemoryStore(db)
    first = store.save_fact(
        user_id="u1",
        session_id=None,
        subject="theme",
        content="light",
        confidence=0.9,
    )
    second = store.save_fact(
        user_id="u1",
        session_id=None,
        subject="theme",
        content="dark",
        confidence=0.9,
    )
    assert second.status == "needs_review"
    confirmed = store.confirm_fact(second.id)
    assert confirmed is not None
    assert confirmed.status == "active"
    assert store.get(first.id).status == "superseded"


def test_summarizer_keeps_structured_summary(db: Database) -> None:
    summarizer = MemorySummarizer(db)
    summarizer.update(
        "sess_1",
        user_text="目标是重构 payment 模块\n决定采用构造函数注入",
        response_text="已完成策略模式拆分",
    )
    summary = summarizer.get("sess_1")
    assert any("重构 payment" in item for item in summary["goals"])
    assert any("构造函数注入" in item for item in summary["decisions"])
    assert any("策略模式" in item for item in summary["progress"])


def test_consolidator_creates_knowledge_facts(db: Database) -> None:
    session = SessionManager(db).create("u1", "consolidation")
    summarizer = MemorySummarizer(db)
    summarizer.update(session.id, user_text="偏好使用 Python", response_text="已记录")
    result = MemoryConsolidator(db).consolidate("u1", window=10)
    assert result.saved >= 1
    facts = MemoryStore(db).search("u1", "Python")
    assert any(fact.kind == "knowledge" for fact in facts)


def test_compressor_applies_l1_l2_l3(db: Database) -> None:
    compressor = MemoryCompressor(db)
    messages = [
        {"role": "user", "content": "取消这个操作", "id": "drop_1", "drop_low_value": True},
        {"role": "tool", "content": "x" * 1200, "id": "tool_1"},
        *[{"role": "user", "content": f"旧问题 {i}", "id": f"old_user_{i}"} for i in range(3)],
        *[
            {"role": "assistant", "content": f"旧回答 {i}", "id": f"old_assistant_{i}"}
            for i in range(3)
        ],
        {"role": "user", "content": "最新问题", "id": "user_2"},
        {"role": "assistant", "content": "最新回答", "id": "assistant_2"},
    ]
    summary = {
        "goals": ["重构模块"],
        "progress": ["已完成拆分"],
        "decisions": ["采用依赖注入"],
        "key_facts": ["测试命令 pytest"],
    }
    outcome = compressor.compress("sess_1", token_budget=50, messages=messages, summary=summary)
    assert 1 in outcome.result.levels_used
    assert 2 in outcome.result.levels_used
    assert 3 in outcome.result.levels_used
    assert any(message["role"] == "summary" for message in outcome.context_messages)


def test_retriever_respects_limit(db: Database) -> None:
    store = MemoryStore(db)
    for index in range(3):
        store.save_fact(
            user_id="u1",
            session_id=None,
            subject=f"python-{index}",
            content=f"python preference {index}",
            tags=["language"],
        )
    facts = MemoryRetriever(store).retrieve(
        user_id="u1",
        query="python",
        limit=2,
    )
    assert len(facts) == 2
