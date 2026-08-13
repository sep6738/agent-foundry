"""Deterministic no-vector scoring for structured memory retrieval."""

from __future__ import annotations

import math
import re
from datetime import UTC, datetime
from typing import Any

_TOKEN_SPLIT = re.compile(r"[\W_]+", re.UNICODE)
_SCOPE_BOOST = {"session": 1.0, "project": 0.8, "user": 0.6}


def extract_keywords(text: str, limit: int = 12) -> list[str]:
    """Best-effort keyword extraction: ASCII tokens plus whole-word candidates."""
    tokens = [t for t in _TOKEN_SPLIT.split(text.lower()) if t and len(t) >= 2]
    keywords = list(dict.fromkeys(tokens))
    if not keywords and len(text.strip()) >= 2:
        keywords.append(text.strip().lower())
    return keywords[:limit]


def score_fact(fact: dict[str, Any], query: str, now: datetime | None = None) -> float:
    """Score a fact by keyword, subject, tag, recency, importance, scope, confidence."""
    now = now or datetime.now(UTC)
    query_lower = query.strip().lower()
    if not query_lower:
        return 0.0

    subject = str(fact.get("subject") or "").lower()
    content = str(fact.get("content") or "").lower()
    tags = " ".join(str(tag) for tag in (fact.get("tags") or []))
    keywords = " ".join(str(kw) for kw in (fact.get("keywords") or []))
    haystack = f"{subject} {content} {tags} {keywords}".lower()

    keyword_hit = 0.0
    for token in _TOKEN_SPLIT.split(query_lower):
        if len(token) >= 2 and token in haystack:
            keyword_hit = 1.0
            break
    if keyword_hit == 0.0 and query_lower in haystack:
        keyword_hit = 0.6

    subject_hit = 1.0 if query_lower in subject or subject in query_lower else 0.0
    tag_hit = 1.0 if query_lower in tags else 0.0

    last_access = fact.get("last_access_at")
    recency = 0.0
    if isinstance(last_access, datetime):
        if last_access.tzinfo is None:
            last_access = last_access.replace(tzinfo=UTC)
        days = max(0.0, (now - last_access).total_seconds() / 86400)
        recency = math.exp(-days / 30)

    importance = float(fact.get("importance") or 0.5)
    confidence = float(fact.get("confidence") or 0.7)
    scope_boost = _SCOPE_BOOST.get(str(fact.get("scope") or "user"), 0.5)
    rank = max(0.0, min(1.0, float(fact.get("rank") or 0.0)))

    score = (
        0.4 * keyword_hit
        + 0.2 * subject_hit
        + 0.1 * tag_hit
        + 0.1 * recency
        + 0.1 * importance
        + 0.05 * scope_boost
        + 0.05 * confidence
        + 0.1 * rank
    )
    return round(score, 4)
