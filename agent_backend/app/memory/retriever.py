"""Budget-aware memory retrieval built on the structured fact store."""

from __future__ import annotations

from agent_backend.app.memory.store import MemoryFact, MemoryStore


def _estimate_tokens(text: str) -> int:
    return max(1, int(len(text) / 4))


class MemoryRetriever:
    def __init__(self, store: MemoryStore) -> None:
        self.store = store

    def retrieve(
        self,
        *,
        user_id: str,
        query: str,
        budget_tokens: int = 500,
        limit: int = 5,
    ) -> list[MemoryFact]:
        facts = self.store.search(user_id, query, limit=limit * 3)
        selected: list[MemoryFact] = []
        used = 0
        for fact in facts:
            cost = _estimate_tokens(fact.content)
            if used + cost > budget_tokens and selected:
                break
            selected.append(fact)
            used += cost
            if len(selected) >= limit:
                break
        return selected
