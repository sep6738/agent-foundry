"""Small request payload validation helpers."""

from __future__ import annotations

from typing import Any


def require_fields(data: dict[str, Any], fields: tuple[str, ...]) -> list[str]:
    return [name for name in fields if not str(data.get(name, "")).strip()]


def parse_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return default
