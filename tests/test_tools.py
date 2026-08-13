"""Tool runner tests."""

from __future__ import annotations

from pathlib import Path

from agent_backend.app.tools.builtin import build_builtin_tools
from agent_backend.app.tools.executor import ToolExecutor, ToolHooks
from agent_backend.app.tools.registry import Tool, ToolContext, ToolRegistry, ToolRunner


async def test_runner_rejects_invalid_args(tmp_path: Path) -> None:
    registry = ToolRegistry(build_builtin_tools())
    runner = ToolRunner(registry, ToolContext(project_root=tmp_path))
    result = await runner.run("read_file", {})
    assert result["ok"] is False
    assert "invalid arguments" in result["error"]


async def test_runner_lists_directory(tmp_path: Path) -> None:
    (tmp_path / "hello.txt").write_text("hello", encoding="utf-8")
    registry = ToolRegistry(build_builtin_tools())
    runner = ToolRunner(registry, ToolContext(project_root=tmp_path))
    result = await runner.run("list_directory", {"path": "."})
    assert result["ok"] is True
    assert "hello.txt" in result["output"]


async def test_runner_marks_error_result_not_ok(tmp_path: Path) -> None:
    async def fail(_context, _args):
        return {"error": "boom"}

    registry = ToolRegistry([Tool(name="fail", description="fail", parameters={}, handler=fail)])
    runner = ToolRunner(registry, ToolContext(project_root=tmp_path))
    result = await runner.run("fail", {})
    assert result["ok"] is False
    assert "boom" in result["error"]


async def test_executor_runs_before_and_after_hooks(tmp_path: Path) -> None:
    registry = ToolRegistry(build_builtin_tools())
    runner = ToolRunner(registry, ToolContext(project_root=tmp_path))
    calls = []
    hooks = ToolHooks(
        before=lambda name, args: calls.append(("before", name)),
        after=lambda name, args, result: calls.append(("after", name)),
    )
    executor = ToolExecutor(runner, hooks)
    result = await executor.run("list_directory", {"path": "."})
    assert result["ok"] is True
    assert calls == [("before", "list_directory"), ("after", "list_directory")]


async def test_run_command_executes_inside_project(tmp_path: Path) -> None:
    registry = ToolRegistry(build_builtin_tools())
    runner = ToolRunner(
        registry,
        ToolContext(project_root=tmp_path, terminal_timeout_seconds=10),
    )
    result = await runner.run("run_command", {"command": "echo command-ok"})
    assert result["ok"] is True
    assert "command-ok" in result["output"]


async def test_run_command_blocks_project_escape(tmp_path: Path) -> None:
    registry = ToolRegistry(build_builtin_tools())
    runner = ToolRunner(
        registry,
        ToolContext(project_root=tmp_path, terminal_timeout_seconds=10),
    )
    result = await runner.run("run_command", {"command": "cd .. && dir"})
    assert result["ok"] is False
    assert "越过项目目录" in result["error"]


async def test_run_command_emits_terminal_events(tmp_path: Path) -> None:
    events = []

    def sink(event_type: str, payload: dict) -> None:
        events.append((event_type, payload))

    registry = ToolRegistry(build_builtin_tools())
    runner = ToolRunner(
        registry,
        ToolContext(
            project_root=tmp_path,
            terminal_timeout_seconds=10,
            event_sink=sink,
        ),
    )
    result = await runner.run("run_command", {"command": "echo stream-ok"})
    assert result["ok"] is True
    event_types = [event_type for event_type, _ in events]
    assert "command_started" in event_types
    assert "command_stdout" in event_types
    assert "command_finished" in event_types
    assert any("stream-ok" in payload.get("line", "") for _, payload in events)


async def test_write_file_is_git_backed(tmp_path: Path) -> None:
    registry = ToolRegistry(build_builtin_tools())
    runner = ToolRunner(
        registry,
        ToolContext(project_root=tmp_path, git_backed_writes=True),
    )
    result = await runner.run(
        "write_file",
        {"path": "notes/readme.md", "content": "# hello"},
    )
    assert result["ok"] is True
    assert result.get("git_commit")
    assert (tmp_path / "notes" / "readme.md").is_file()
    assert (tmp_path / ".git").exists()
