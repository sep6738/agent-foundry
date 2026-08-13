"""Run scenario-based evaluations against the runtime with an isolated database."""

from __future__ import annotations

import json
import queue
import sys
import tempfile
from pathlib import Path

from agent_backend.app import create_app
from agent_backend.app.config import Settings
from agent_backend.app.core.runtime import AgentRuntime


def main() -> int:
    temp_dir = Path(tempfile.mkdtemp(prefix="agent-evals-"))
    settings = Settings(
        app_env="eval",
        database_url=f"sqlite:///{temp_dir / 'eval.db'}",
        model_provider="stub",
        project_root=Path.cwd(),
        human_approval_required=True,
    )
    app = create_app(settings)
    runtime_context = app.extensions["runtime_context"]
    manager = runtime_context.session_manager
    runtime = AgentRuntime(runtime_context)

    failures = 0
    for scenario_file in sorted(Path(__file__).parent.glob("scenarios/*.json")):
        scenario = json.loads(scenario_file.read_text(encoding="utf-8"))
        session = manager.create("eval", scenario["name"])
        subscriber = runtime_context.event_bus.subscribe()
        for setup_prompt in scenario.get("setup", []):
            runtime.run_turn(
                session_id=session.id,
                user_id="eval",
                text=setup_prompt,
                thread_id=session.thread_id,
            )
        result = runtime.run_turn(
            session_id=session.id,
            user_id="eval",
            text=scenario["prompt"],
            thread_id=session.thread_id,
        )
        events = []
        while True:
            try:
                event = subscriber.get_nowait()
            except queue.Empty:
                break
            if event is None:
                break
            if event.session_id == session.id:
                events.append(event)
        runtime_context.event_bus.unsubscribe(subscriber)

        response = str(result.get("response", ""))
        ok = all(word in response for word in scenario.get("expected", []))
        expected_tool = scenario.get("tool_usage")
        if expected_tool:
            used_tool = any(
                event.type == "tool_call_started" and event.payload.get("tool") == expected_tool
                for event in events
            )
            ok = used_tool and ok
        expected_events = scenario.get("expected_events", [])
        event_types = {event.type for event in events}
        ok = ok and all(name in event_types for name in expected_events)
        print(f"{'PASS' if ok else 'FAIL'} {scenario['name']}")
        failures += 0 if ok else 1
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
