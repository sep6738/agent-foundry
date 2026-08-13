"""Claude Code style four-level progressive context compression."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from langchain_core.messages import HumanMessage

from agent_backend.app.storage.database import Database
from agent_backend.app.storage.models import CompressionRecord, new_id

logger = logging.getLogger(__name__)


@dataclass
class CompressionResult:
    levels_used: list[int]
    tokens_before: int
    tokens_after: int
    removed_entry_ids: list[str]
    replaced_entry_ids: list[str]
    summary_id: str | None = None
    kept_window_entries: int = 0
    cache_invalidated: bool = False


@dataclass
class CompressionOutcome:
    result: CompressionResult
    context_messages: list[dict[str, Any]] = field(default_factory=list)


def estimate_tokens(text: str) -> int:
    return max(1, int(len(text) / 4))


def _render_summary(summary: dict[str, Any] | None) -> str:
    if not summary:
        return ""
    parts: list[str] = ["<session_summary>"]
    for key in ("goals", "progress", "decisions", "open_questions", "key_facts"):
        items = summary.get(key) or []
        if items:
            parts.append(f"<{key}>")
            parts.extend(f"- {item}" for item in items)
            parts.append(f"</{key}>")
    parts.append("</session_summary>")
    return "\n".join(parts)


class MemoryCompressor:
    """Applies L1 drop, L2 tool-output trimming, L3 summary replacement, L4 model fallback."""

    def __init__(self, db: Database) -> None:
        self.db = db

    def should_compress(self, token_budget: int, current_tokens: int, ratio: float = 0.9) -> bool:
        return current_tokens > token_budget * ratio

    def compress(
        self,
        session_id: str,
        token_budget: int,
        messages: list[dict[str, Any]],
        summary: dict[str, Any] | None = None,
        *,
        model=None,
        trigger: str = "budget_warning",
    ) -> CompressionOutcome:
        working = [dict(message) for message in messages]
        levels: list[int] = []
        removed: list[str] = []
        replaced: list[str] = []
        before = sum(estimate_tokens(str(m.get("content", ""))) for m in working)

        # L1: drop low-value turns and empty tool results.
        filtered: list[dict[str, Any]] = []
        for message in working:
            role = str(message.get("role", ""))
            content = str(message.get("content", ""))
            if message.get("drop_low_value") or (role == "tool" and not content.strip()):
                removed.append(str(message.get("id", "")))
                levels.append(1)
                continue
            filtered.append(message)
        working = filtered

        # L2: replace older long tool output with a pointer to L0.
        for idx, message in enumerate(working):
            role = str(message.get("role", ""))
            content = str(message.get("content", ""))
            is_recent = idx >= len(working) - 2
            if role == "tool" and len(content) > 800 and not is_recent:
                message["content"] = (
                    f"[原始输出已清理，见 session_entries: {message.get('id', '')}]\n"
                    + content[:400]
                )
                replaced.append(str(message.get("id", "")))
                levels.append(2)

        after_local = sum(estimate_tokens(str(m.get("content", ""))) for m in working)
        ratio_ok = after_local <= token_budget * 0.9
        summary_text = _render_summary(summary)
        kept_window = 0
        summary_id = None

        # L3: replace pre-window history with the maintained running summary.
        if not ratio_ok and summary_text:
            cut = max(0, len(working) - 6)
            while cut < len(working) and str(working[cut].get("role", "")) == "tool":
                cut += 1
            if cut > 0:
                kept_window = len(working) - cut
                removed.extend(str(m.get("id", "")) for m in working[:cut] if m.get("id"))
                summary_id = (summary or {}).get("last_updated_entry_id")
                working = [
                    {
                        "role": "summary",
                        "content": summary_text,
                        "id": f"summary_{session_id[:16]}",
                    }
                ] + working[cut:]
                levels.append(3)

        after_medium = sum(estimate_tokens(str(m.get("content", ""))) for m in working)

        # L4: only when explicitly allowed and a real model is configured.
        if after_medium > token_budget * 0.9 and model is not None:
            try:
                prompt = (
                    "把以下对话压缩成结构化摘要，保留目标、进度、决策、待办和关键事实：\n"
                    + "\n".join(f"{m.get('role')}: {m.get('content')}" for m in working[:-6])[:8000]
                )
                result = model.invoke([HumanMessage(content=prompt)])
                summary_text = str(result.content)
                cut = max(0, len(working) - 6)
                while cut < len(working) and str(working[cut].get("role", "")) == "tool":
                    cut += 1
                if cut > 0:
                    kept_window = len(working) - cut
                    removed.extend(str(m.get("id", "")) for m in working[:cut] if m.get("id"))
                    working = [
                        {
                            "role": "summary",
                            "content": summary_text,
                            "id": f"model_summary_{session_id[:16]}",
                        }
                    ] + working[cut:]
                    levels.append(4)
            except Exception:  # noqa: BLE001
                logger.warning("model compression fallback failed", exc_info=True)

        after = sum(estimate_tokens(str(m.get("content", ""))) for m in working)
        if not levels:
            return CompressionOutcome(
                result=CompressionResult(
                    levels_used=[],
                    tokens_before=before,
                    tokens_after=after,
                    removed_entry_ids=[],
                    replaced_entry_ids=[],
                    summary_id=summary_id,
                    kept_window_entries=kept_window,
                ),
                context_messages=working,
            )

        with self.db.transaction() as session:
            record = CompressionRecord(
                id=new_id("cmp"),
                session_id=session_id,
                levels_used=sorted(set(levels)),
                tokens_before=before,
                tokens_after=after,
                summary_id=summary_id,
                removed_entry_ids=removed,
                replaced_entry_ids=replaced,
                kept_window_entries=kept_window,
                cache_invalidated=bool(levels),
            )
            session.add(record)
            session.flush()

        return CompressionOutcome(
            result=CompressionResult(
                levels_used=sorted(set(levels)),
                tokens_before=before,
                tokens_after=after,
                removed_entry_ids=removed,
                replaced_entry_ids=replaced,
                summary_id=summary_id,
                kept_window_entries=kept_window,
                cache_invalidated=bool(levels),
            ),
            context_messages=working,
        )
