"""Thread-safe trace id propagation for observability events."""

from __future__ import annotations

from contextvars import ContextVar

_current_trace_id: ContextVar[str | None] = ContextVar("agent_trace_id", default=None)


def set_trace_id(trace_id: str | None) -> object:
    return _current_trace_id.set(trace_id)


def get_trace_id() -> str | None:
    return _current_trace_id.get()


def reset_trace_id(token: object) -> None:
    _current_trace_id.reset(token)
