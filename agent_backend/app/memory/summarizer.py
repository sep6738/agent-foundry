"""Rule-based running session summary maintenance (zero API cost)."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select

from agent_backend.app.storage.database import Database
from agent_backend.app.storage.models import SessionSummary, new_id

_GOAL_MARKERS = ("目标", "重构", "实现", "修复", "添加", "优化", "迁移", "调研")
_DECISION_MARKERS = ("决定", "采用", "选择", "确认", "改为", "使用")
_PROGRESS_MARKERS = ("完成", "已经", "已实现", "已修复", "搞定")
_FACT_MARKERS = ("测试命令", "偏好", "喜欢", "使用", "需要", "禁止", "注意")


def _extract_goal(text: str) -> list[str]:
    return [
        line.strip()
        for line in text.splitlines()
        if any(marker in line for marker in _GOAL_MARKERS)
    ][:3]


def _extract_decision(text: str) -> list[str]:
    return [
        line.strip()
        for line in text.splitlines()
        if any(marker in line for marker in _DECISION_MARKERS)
    ][:3]


def _extract_progress(text: str) -> list[str]:
    return [
        line.strip()
        for line in text.splitlines()
        if any(marker in line for marker in _PROGRESS_MARKERS)
    ][:3]


def _extract_open_questions(text: str) -> list[str]:
    return [
        line.strip()
        for line in text.splitlines()
        if line.strip().endswith("?") or line.strip().endswith("？")
    ][:3]


def _extract_key_facts(text: str) -> list[str]:
    return [
        line.strip()
        for line in text.splitlines()
        if any(marker in line for marker in _FACT_MARKERS)
    ][:5]


def _dedupe(items: list[str], limit: int = 10) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        key = re.sub(r"\s+", " ", item).strip().lower()
        if key and key not in seen:
            seen.add(key)
            result.append(item)
    return result[-limit:]


class MemorySummarizer:
    """Maintains the structured L2 summary used by L3 compression."""

    def __init__(self, db: Database) -> None:
        self.db = db

    def update(
        self,
        session_id: str,
        *,
        user_text: str,
        response_text: str,
        entry_id: str | None = None,
    ) -> dict[str, Any]:
        with self.db.transaction() as session:
            summary = (
                session.execute(
                    select(SessionSummary)
                    .where(SessionSummary.session_id == session_id)
                    .order_by(SessionSummary.updated_at.desc())
                )
                .scalars()
                .first()
            )
            if summary is None:
                summary = SessionSummary(
                    id=new_id("sum"),
                    session_id=session_id,
                    summary={
                        "goals": [],
                        "progress": [],
                        "decisions": [],
                        "open_questions": [],
                        "key_facts": [],
                    },
                )
                session.add(summary)
            data = dict(summary.summary or {})
            data.setdefault("goals", [])
            data.setdefault("progress", [])
            data.setdefault("decisions", [])
            data.setdefault("open_questions", [])
            data.setdefault("key_facts", [])
            data["goals"] = _dedupe(data["goals"] + _extract_goal(user_text))
            data["progress"] = _dedupe(
                data["progress"] + _extract_progress(user_text) + _extract_progress(response_text)
            )
            data["decisions"] = _dedupe(
                data["decisions"] + _extract_decision(user_text) + _extract_decision(response_text)
            )
            data["open_questions"] = _dedupe(
                data["open_questions"] + _extract_open_questions(user_text)
            )
            data["key_facts"] = _dedupe(
                data["key_facts"]
                + _extract_key_facts(user_text)
                + _extract_key_facts(response_text)
            )
            data["last_updated_at"] = datetime.now(UTC).isoformat()
            if entry_id:
                data["last_updated_entry_id"] = entry_id
            summary.summary = data
            session.flush()
            return dict(data)

    def get(self, session_id: str) -> dict[str, Any]:
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
            return dict(summary.summary or {}) if summary else {}
