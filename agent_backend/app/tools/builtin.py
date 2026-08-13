"""Safe built-in tools for project inspection."""

from __future__ import annotations

import asyncio
import os
import subprocess
from pathlib import Path
from typing import Any

from agent_backend.app.skills.registry import SkillRegistry
from agent_backend.app.skills.runner import SkillRunner
from agent_backend.app.tools.audit import command_escapes_project
from agent_backend.app.tools.registry import Tool, ToolContext


def _resolve(context: ToolContext, path_value: str) -> Path:
    root = context.project_root.resolve()
    path = (root / path_value).resolve()
    if root not in path.parents and path != root:
        raise ValueError("path escapes project root")
    return path


async def list_directory(context: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    path = _resolve(context, str(args.get("path", ".")))
    if not path.is_dir():
        return {"ok": False, "error": f"not a directory: {path}"}
    entries = [
        {
            "name": entry.name,
            "type": "dir" if entry.is_dir() else "file",
        }
        for entry in sorted(path.iterdir())
    ]
    return {"ok": True, "output": "\n".join(f"{e['type']}\t{e['name']}" for e in entries)}


async def read_file(context: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    path = _resolve(context, str(args["path"]))
    if not path.is_file():
        return {"ok": False, "error": f"not a file: {path}"}
    content = path.read_text(encoding="utf-8", errors="replace")
    return {"ok": True, "output": content, "path": str(path)}


async def write_file(context: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    path = _resolve(context, str(args["path"]))
    if path.is_dir():
        return {"ok": False, "error": f"path is a directory: {path}"}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(str(args["content"]), encoding="utf-8")
    result: dict[str, Any] = {"ok": True, "output": f"wrote file: {path}", "path": str(path)}
    if context.git_backed_writes:
        commit = _git_write(context.project_root, path)
        if commit:
            result["git_commit"] = commit
            result["output"] += f"\ngit commit: {commit}"
    return result


def _git_write(project_root: Path, path: Path) -> str | None:
    _ensure_git_repo(project_root)
    relative = os.path.relpath(path, project_root).replace("\\", "/")
    add = _run_git(project_root, "add", "--", relative)
    if add is None:
        return None
    message = f"agent: {relative}"
    commit = _run_git(project_root, "commit", "-m", message)
    return commit.strip().splitlines()[-1] if commit and commit.strip() else None


def _ensure_git_repo(project_root: Path) -> None:
    if (project_root / ".git").exists():
        return
    _run_git(project_root, "init")
    _run_git(project_root, "config", "user.name", "Agent")
    _run_git(project_root, "config", "user.email", "agent@local")


def _run_git(project_root: Path, *args: str) -> str | None:
    try:
        completed = subprocess.run(
            ["git", *args],
            cwd=project_root,
            capture_output=True,
            text=True,
            timeout=30,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (subprocess.TimeoutExpired, OSError):
        return None
    return completed.stdout.strip() if completed.returncode == 0 else None


async def run_command(context: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    command = str(args.get("command", "")).strip()
    if not command:
        return {"ok": False, "error": "command is required"}
    if command_escapes_project(command, context.project_root):
        return {
            "ok": False,
            "error": "命令试图越过项目目录，已阻止执行",
        }
    timeout = int(args.get("timeout", context.terminal_timeout_seconds))
    creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        process = await asyncio.create_subprocess_shell(
            command,
            cwd=context.project_root,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            creationflags=creation_flags,
        )
    except OSError as exc:
        return {"ok": False, "error": str(exc)}

    if context.event_sink is not None:
        context.event_sink(
            "command_started",
            {"command": command, "pid": process.pid, "cwd": str(context.project_root)},
        )
    stdout_lines: list[str] = []
    stderr_lines: list[str] = []
    timed_out = False
    try:
        async with asyncio.timeout(timeout):
            if process.stdout is not None and process.stderr is not None:

                async def read_stream(stream, sink_type, lines):
                    async for raw in stream:
                        raw_text = (
                            raw.decode("utf-8", errors="replace")
                            if isinstance(raw, bytes)
                            else str(raw)
                        )
                        line = raw_text.rstrip("\r\n")
                        if not line:
                            continue
                        lines.append(line)
                        if context.event_sink is not None:
                            context.event_sink(sink_type, {"line": line})

                await asyncio.gather(
                    read_stream(process.stdout, "command_stdout", stdout_lines),
                    read_stream(process.stderr, "command_stderr", stderr_lines),
                )
            returncode = await process.wait()
    except TimeoutError:
        timed_out = True
        process.kill()
        returncode = -1

    output = "\n".join(stdout_lines)
    stderr = "\n".join(stderr_lines)
    if context.event_sink is not None:
        context.event_sink(
            "command_finished",
            {
                "exit_code": returncode,
                "timed_out": timed_out,
                "stdout": output[-2000:],
                "stderr": stderr[-2000:],
            },
        )
    if timed_out:
        return {"ok": False, "error": "command timed out", "output": output, "stderr": stderr}
    if returncode != 0:
        return {
            "ok": False,
            "error": stderr or f"exit code {returncode}",
            "output": output,
        }
    return {"ok": True, "output": output, "stderr": stderr}


async def read_skill(context: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    registry: SkillRegistry | None = context.skill_registry
    if registry is None:
        return {"ok": False, "error": "skill registry is not configured"}
    skill = registry.get_skill(
        str(args["name"]),
        context.project_root,
        user_home=context.user_home,
    )
    if skill is None:
        return {"ok": False, "error": f"skill not found: {args['name']}"}
    return {"ok": True, "output": skill.content, "path": skill.meta.source_path}


async def edit_skill(context: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    registry: SkillRegistry | None = context.skill_registry
    if registry is None:
        return {"ok": False, "error": "skill registry is not configured"}
    try:
        skill = registry.save(
            str(args["name"]),
            str(args["content"]),
            context.project_root,
            scope=str(args.get("scope", "project")),
            user_home=context.user_home,
        )
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}
    return {"ok": True, "output": f"skill saved: {skill.meta.name}"}


async def run_skill_script(context: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    registry: SkillRegistry | None = context.skill_registry
    if registry is None:
        return {"ok": False, "error": "skill registry is not configured"}
    skill = registry.get_skill(
        str(args["skill"]),
        context.project_root,
        user_home=context.user_home,
    )
    if skill is None:
        return {"ok": False, "error": f"skill not found: {args['skill']}"}
    return SkillRunner().run_script(
        skill,
        str(args["script"]),
        args=list(args.get("args") or []),
    )


def build_builtin_tools() -> list[Tool]:
    return [
        Tool(
            name="list_directory",
            description="List entries in a directory inside the project root.",
            parameters={
                "type": "object",
                "properties": {"path": {"type": "string", "default": "."}},
            },
            handler=list_directory,
            permissions={"filesystem:read"},
        ),
        Tool(
            name="read_file",
            description="Read a text file inside the project root.",
            parameters={
                "type": "object",
                "required": ["path"],
                "properties": {"path": {"type": "string"}},
            },
            handler=read_file,
            permissions={"filesystem:read"},
        ),
        Tool(
            name="write_file",
            description="Write a UTF-8 text file inside the project root.",
            parameters={
                "type": "object",
                "required": ["path", "content"],
                "properties": {
                    "path": {"type": "string"},
                    "content": {"type": "string"},
                },
            },
            handler=write_file,
            permissions={"filesystem:write"},
        ),
        Tool(
            name="run_command",
            description=(
                "Run a terminal command inside the project folder. "
                "Commands cannot escape the project folder."
            ),
            parameters={
                "type": "object",
                "required": ["command"],
                "properties": {
                    "command": {"type": "string"},
                    "timeout": {"type": "integer", "minimum": 1},
                },
            },
            handler=run_command,
            timeout_seconds=120,
            permissions={"exec:command"},
        ),
        Tool(
            name="read_skill",
            description="Read the full SKILL.md content for a named skill.",
            parameters={
                "type": "object",
                "required": ["name"],
                "properties": {"name": {"type": "string"}},
            },
            handler=read_skill,
            permissions={"skills:read"},
        ),
        Tool(
            name="edit_skill",
            description="Create or update a reusable SKILL.md skill.",
            parameters={
                "type": "object",
                "required": ["name", "content"],
                "properties": {
                    "name": {"type": "string"},
                    "content": {"type": "string"},
                    "scope": {"type": "string", "default": "project"},
                },
            },
            handler=edit_skill,
            permissions={"skills:write"},
        ),
        Tool(
            name="run_skill_script",
            description="Run a .py script bundled inside a skill's scripts/ directory.",
            parameters={
                "type": "object",
                "required": ["skill", "script"],
                "properties": {
                    "skill": {"type": "string"},
                    "script": {"type": "string"},
                    "args": {"type": "array", "items": {"type": "string"}},
                },
            },
            handler=run_skill_script,
            permissions={"exec:skill"},
        ),
    ]
