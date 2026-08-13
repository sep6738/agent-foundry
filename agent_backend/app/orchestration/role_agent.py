"""LLM-backed role agents with deterministic fallbacks."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any, TypeVar

from langchain_core.messages import HumanMessage

from agent_backend.app.core.context import RuntimeContext
from agent_backend.app.core.model import build_chat_model

T = TypeVar("T")


def parse_json_object(text: str) -> dict[str, Any] | None:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        lines = cleaned.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        cleaned = "\n".join(lines).strip()
    try:
        parsed = json.loads(cleaned)
        return parsed if isinstance(parsed, dict) else None
    except json.JSONDecodeError:
        pass
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start >= 0 and end > start:
        try:
            parsed = json.loads(cleaned[start : end + 1])
            return parsed if isinstance(parsed, dict) else None
        except json.JSONDecodeError:
            return None
    return None


class RoleAgent:
    """Runs a prompt through the configured model, falling back to rules."""

    def __init__(self, context: RuntimeContext) -> None:
        self.context = context

    def run(
        self,
        prompt: str,
        parser: Callable[[str], T | None],
        fallback: Callable[[], T],
    ) -> T:
        settings = self.context.settings
        if settings.model_provider == "stub" or not settings.model_api_key:
            return fallback()
        try:
            model = build_chat_model(settings)
            result = model.invoke([HumanMessage(content=prompt)])
            parsed = parser(str(result.content))
            return parsed if parsed is not None else fallback()
        except Exception:  # noqa: BLE001
            return fallback()
