"""In-memory event bus with database persistence."""

from __future__ import annotations

import logging
import queue
import threading
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from agent_backend.app.observability.trace import get_trace_id
from agent_backend.app.storage.database import Database
from agent_backend.app.storage.models import Event as EventRow
from agent_backend.app.storage.models import new_id

logger = logging.getLogger(__name__)


@dataclass
class Event:
    type: str
    payload: dict[str, Any] = field(default_factory=dict)
    session_id: str | None = None
    trace_id: str | None = field(default_factory=get_trace_id)
    ts: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def to_sse(self) -> str:
        import json

        data = json.dumps(
            {
                "type": self.type,
                "payload": self.payload,
                "trace_id": self.trace_id,
                "ts": self.ts,
            },
            ensure_ascii=False,
        )
        return f"event: {self.type}\ndata: {data}\n\n"


class EventBus:
    def __init__(self, db: Database | None = None) -> None:
        self.db = db
        self._subscribers: list[queue.Queue[Event | None]] = []
        self._lock = threading.Lock()

    def publish(self, event: Event) -> None:
        if self.db is not None:
            try:
                with self.db.transaction() as session:
                    session.add(
                        EventRow(
                            id=new_id("evt"),
                            session_id=event.session_id,
                            type=event.type,
                            payload={
                                **event.payload,
                                "trace_id": event.trace_id,
                            },
                        )
                    )
            except Exception:
                logger.warning("failed to persist event %s", event.type, exc_info=True)
        with self._lock:
            for subscriber in self._subscribers:
                subscriber.put(event)

    def subscribe(self) -> queue.Queue[Event | None]:
        subscriber: queue.Queue[Event | None] = queue.Queue()
        with self._lock:
            self._subscribers.append(subscriber)
        return subscriber

    def unsubscribe(self, subscriber: queue.Queue[Event | None]) -> None:
        with self._lock:
            if subscriber in self._subscribers:
                self._subscribers.remove(subscriber)

    def close(self) -> None:
        with self._lock:
            for subscriber in self._subscribers:
                subscriber.put(None)
            self._subscribers.clear()
