"""Tool execution pipeline with before/after hooks."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from agent_backend.app.tools.registry import ToolContext, ToolRunner


@dataclass
class ToolHooks:
    before: Callable[[str, dict[str, Any]], None] | None = None
    after: Callable[[str, dict[str, Any], dict[str, Any]], None] | None = None


class ToolExecutor:
    def __init__(
        self,
        runner: ToolRunner,
        hooks: ToolHooks | None = None,
        retries: int = 0,
    ) -> None:
        self.runner = runner
        self.hooks = hooks or ToolHooks()
        self.retries = retries

    async def run(
        self,
        tool_name: str,
        args: dict[str, Any],
        context: ToolContext | None = None,
    ) -> dict[str, Any]:
        last: dict[str, Any] = {"ok": False, "error": "unknown error"}
        for attempt in range(self.retries + 1):
            if self.hooks.before is not None:
                self.hooks.before(tool_name, args)
            last = await self.runner.run(tool_name, args, context=context)
            if self.hooks.after is not None:
                self.hooks.after(tool_name, args, last)
            if last.get("ok") or not self._retryable(last):
                return last
            if attempt < self.retries:
                await asyncio.sleep(0.2 * (attempt + 1))
        return last

    @staticmethod
    def _retryable(result: dict[str, Any]) -> bool:
        error = str(result.get("error", "")).lower()
        return any(marker in error for marker in ("timed out", "timeout", "connection"))
