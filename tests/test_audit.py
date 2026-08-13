"""Tool audit policy tests."""

from __future__ import annotations

from pathlib import Path

from agent_backend.app.tools.audit import audit_tool_call, command_escapes_project
from agent_backend.app.tools.registry import Tool


def _tool(name: str, permissions: set[str]) -> Tool:
    return Tool(
        name=name,
        description=name,
        parameters={},
        handler=lambda context, args: {},
        permissions=permissions,
    )


def test_write_file_requires_approval_only_at_level_one() -> None:
    tool = _tool("write_file", {"filesystem:write"})
    assert audit_tool_call(tool, {"path": "a.txt"}, 1).requires_approval is True
    assert audit_tool_call(tool, {"path": "a.txt"}, 2).requires_approval is False
    assert audit_tool_call(tool, {"path": "a.txt"}, 3).requires_approval is False


def test_read_operations_never_require_approval() -> None:
    tool = _tool("read_file", {"filesystem:read"})
    for level in (1, 2, 3):
        decision = audit_tool_call(tool, {"path": "a.txt"}, level)
        assert decision.requires_approval is False


def test_dangerous_command_is_detected_and_needs_approval_at_level_two() -> None:
    tool = _tool("run_command", {"exec:command"})
    decision = audit_tool_call(tool, {"command": "DROP DATABASE app;"}, 2)
    assert decision.dangerous is True
    assert decision.requires_approval is True
    assert "删除数据库" in decision.risk


def test_dangerous_command_still_notifies_at_level_three() -> None:
    tool = _tool("run_command", {"exec:command"})
    decision = audit_tool_call(tool, {"command": "DROP DATABASE app;"}, 3)
    assert decision.dangerous is True
    assert decision.requires_approval is False


def test_dependency_install_requires_approval_at_level_two() -> None:
    tool = _tool("run_command", {"exec:command"})
    decision = audit_tool_call(tool, {"command": "pip install requests"}, 2)
    assert decision.dangerous is False
    assert decision.requires_approval is True


def test_command_escape_detection(tmp_path: Path) -> None:
    assert command_escapes_project("cd ..", tmp_path) is True
    assert command_escapes_project("dir C:\\Windows", tmp_path) is True
    assert command_escapes_project("pushd C:\\Windows", tmp_path) is True
    assert command_escapes_project("python -m pytest", tmp_path) is False
