"""Tool contract and registry."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

import jsonschema

if TYPE_CHECKING:
    from agent_backend.app.skills.registry import SkillRegistry


EventSink = Callable[[str, dict[str, Any]], None]


@dataclass
class ToolContext:
    project_root: Path
    max_output_bytes: int = 64_000
    skill_registry: SkillRegistry | None = None
    user_home: Path | None = None
    git_backed_writes: bool = True
    terminal_timeout_seconds: int = 30
    event_sink: EventSink | None = None


ToolFunc = Callable[[ToolContext, dict[str, Any]], Awaitable[dict[str, Any]]]


@dataclass
class Tool:
    name: str
    description: str
    parameters: dict[str, Any]
    handler: ToolFunc
    timeout_seconds: int = 30
    permissions: set[str] = field(default_factory=set)

    def to_schema(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


class ToolRegistry:
    def __init__(self, tools: list[Tool] | None = None) -> None:
        self._tools = {tool.name: tool for tool in (tools or [])}

    def register(self, tool: Tool) -> None:
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def list(self) -> list[Tool]:
        return list(self._tools.values())

    def schemas(self) -> list[dict[str, Any]]:
        return [tool.to_schema() for tool in self._tools.values()]


class ToolRunner:
    def __init__(self, registry: ToolRegistry, context: ToolContext) -> None:
        self.registry = registry
        self.context = context

    async def run(
        self,
        tool_name: str,
        args: dict[str, Any],
        context: ToolContext | None = None,
    ) -> dict[str, Any]:
        effective = context or self.context
        tool = self.registry.get(tool_name)
        if tool is None:
            return {"ok": False, "tool": tool_name, "error": f"unknown tool: {tool_name}"}
        try:
            jsonschema.validate(args, tool.parameters)
        except jsonschema.ValidationError as exc:
            return {"ok": False, "tool": tool_name, "error": f"invalid arguments: {exc.message}"}
        started = time.monotonic()
        try:
            result = await asyncio.wait_for(
                tool.handler(effective, args), timeout=tool.timeout_seconds
            )
        except TimeoutError:
            return {"ok": False, "tool": tool_name, "error": "tool timed out"}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "tool": tool_name, "error": str(exc)}
        duration_ms = int((time.monotonic() - started) * 1000)
        output = result.get("output", result.get("content", ""))
        if isinstance(output, str) and len(output) > effective.max_output_bytes:
            result["output"] = output[: effective.max_output_bytes] + "\n[truncated]"
            result["truncated"] = True
        result.setdefault("tool", tool_name)
        result.setdefault("duration_ms", duration_ms)
        result.setdefault("ok", not bool(result.get("error")))
        return result
