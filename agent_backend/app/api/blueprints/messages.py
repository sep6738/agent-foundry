"""SSE message streaming endpoint."""

from __future__ import annotations

import json
import queue
import threading
import time
from typing import Any

from flask import Blueprint, Response, current_app, g, request

from agent_backend.app.api.errors import error
from agent_backend.app.observability.events import Event
from agent_backend.app.services import ConversationService, SessionService

messages_bp = Blueprint("messages", __name__, url_prefix="/v1/sessions")


@messages_bp.post("/<session_id>/messages")
def send_message(session_id: str):
    data = request.get_json(silent=True) or {}
    text = str(data.get("message", "")).strip()
    if not text:
        return error("message is required")
    runtime_context = current_app.extensions["runtime_context"]
    session_service = SessionService(runtime_context)
    conversation_service = ConversationService(runtime_context)
    session = session_service.get(session_id)
    if session is None:
        return error("session not found", 404)
    if session["status"] == "awaiting_human":
        return error("session is waiting for human approval", 409)

    done: queue.Queue[None] = queue.Queue()
    subscriber = runtime_context.event_bus.subscribe()
    result_box: dict[str, Any] = {}
    trace_id = getattr(g, "request_id", None)

    def worker() -> None:
        try:
            result_box["result"] = conversation_service.run_turn(
                session_id=session_id,
                user_id=session["user_id"],
                text=text,
                thread_id=session["thread_id"],
                trace_id=trace_id,
            )
        except Exception as exc:  # noqa: BLE001
            result_box["error"] = str(exc)
        finally:
            done.put(None)

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()

    def stream():
        error_payload = None
        try:
            while True:
                try:
                    event = subscriber.get_nowait()
                except queue.Empty:
                    try:
                        done.get_nowait()
                    except queue.Empty:
                        time.sleep(0.05)
                        continue
                    break
                if event is None:
                    break
                if isinstance(event, Event) and event.session_id == session_id:
                    yield event.to_sse()
        except GeneratorExit:
            raise
        finally:
            runtime_context.event_bus.unsubscribe(subscriber)
            thread.join(timeout=5)
            error_payload = result_box.get("error")
        if error_payload:
            yield (f"event: error\ndata: {json.dumps({'error': error_payload})}\n\n")

    return Response(stream(), mimetype="text/event-stream")
