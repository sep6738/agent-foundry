"""Token usage recording."""

from __future__ import annotations

from datetime import UTC, datetime

from agent_backend.app.observability.trace import get_trace_id
from agent_backend.app.storage.database import Database
from agent_backend.app.storage.models import SessionEntry, new_id


def estimate_tokens(text: str) -> int:
    return max(1, int(len(text) / 4))


class UsageRecorder:
    def __init__(self, db: Database) -> None:
        self.db = db

    def record(self, session_id: str, *, input_text: str, output_text: str) -> None:
        with self.db.transaction() as session:
            session.add(
                SessionEntry(
                    id=new_id("ent"),
                    session_id=session_id,
                    type="usage",
                    payload={
                        "input_tokens": estimate_tokens(input_text),
                        "output_tokens": estimate_tokens(output_text),
                        "trace_id": get_trace_id(),
                        "ts": datetime.now(UTC).isoformat(),
                    },
                )
            )
