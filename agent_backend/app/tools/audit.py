"""Tool audit policy: approval levels, dangerous detection, and risk descriptions."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import IntEnum
from typing import Any


class AuditLevel(IntEnum):
    STRICT = 1
    BALANCED = 2
    TRUST = 3


@dataclass
class AuditDecision:
    requires_approval: bool
    dangerous: bool
    purpose: str
    risk: str = ""
    reason: str = ""


_DANGEROUS_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\bdrop\s+database\b", re.I), "删除数据库（DROP DATABASE）"),
    (re.compile(r"\btruncate\s+(?:table|database)\b", re.I), "清空数据表或数据库"),
    (re.compile(r"\balter\s+(?:table|database|user)\b", re.I), "修改数据库结构或账号"),
    (re.compile(r"\bdelete\s+from\b", re.I), "删除数据库记录"),
    (re.compile(r"\brm\s+-rf\s+(?:/|~)", re.I), "递归删除根目录或主目录"),
    (re.compile(r"\bmkfs\b", re.I), "格式化磁盘文件系统"),
    (re.compile(r"\bformat\s+[a-z]:", re.I), "格式化磁盘分区"),
    (re.compile(r"\bshutdown\b|\breboot\b", re.I), "关机或重启系统"),
    (re.compile(r"\breset-computer\b|\bstop-computer\b", re.I), "重启或关闭计算机"),
    (re.compile(r"\bRemove-Item\b.*-Recurse", re.I), "递归删除文件或目录"),
    (re.compile(r"\bdel\s+/[fq]\s+.*\\", re.I), "强制删除系统路径"),
]

_AUDIT_WORTHY_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\b(?:pip|pip3|pipenv)\s+install\b", re.I), "安装 Python 依赖"),
    (re.compile(r"\bnpm\s+install\b", re.I), "安装 npm 依赖"),
    (re.compile(r"\buv\s+(?:sync|add|install)\b", re.I), "同步或安装 uv 依赖"),
    (re.compile(r"\bpoetry\s+add\b", re.I), "添加 Poetry 依赖"),
    (re.compile(r"\bapt(-get)?\s+install\b", re.I), "安装系统软件包"),
    (re.compile(r"\bbrew\s+install\b", re.I), "安装 Homebrew 软件包"),
    (re.compile(r"\bcurl\b.*(?:--data|-X\s+post)", re.I), "向外部服务提交数据"),
]


def _find_pattern(command: str) -> tuple[re.Pattern[str], str] | None:
    for pattern, description in _DANGEROUS_PATTERNS:
        if pattern.search(command):
            return pattern, description
    return None


def _find_audit_worthy(command: str) -> tuple[re.Pattern[str], str] | None:
    for pattern, description in _AUDIT_WORTHY_PATTERNS:
        if pattern.search(command):
            return pattern, description
    return None


def describe_command(command: str) -> str:
    compact = re.sub(r"\s+", " ", command).strip()
    return compact[:200]


def audit_tool_call(tool, args: dict[str, Any], audit_level: int) -> AuditDecision:
    try:
        level = AuditLevel(int(audit_level))
    except (TypeError, ValueError):
        level = AuditLevel.BALANCED

    if tool.permissions.intersection({"filesystem:read", "skills:read"}):
        return AuditDecision(
            requires_approval=False,
            dangerous=False,
            purpose=f"读取操作：{tool.name}",
        )

    if tool.name == "run_command":
        command = str(args.get("command", ""))
        purpose = f"执行终端命令：{describe_command(command)}"
        danger = _find_pattern(command)
        if danger is not None:
            _, description = danger
            return AuditDecision(
                requires_approval=level != AuditLevel.TRUST,
                dangerous=True,
                purpose=purpose,
                risk=description,
                reason="检测到危险指令",
            )
        worthy = _find_audit_worthy(command)
        if worthy is not None:
            _, description = worthy
            return AuditDecision(
                requires_approval=level in (AuditLevel.STRICT, AuditLevel.BALANCED),
                dangerous=False,
                purpose=purpose,
                risk=description,
                reason="该指令会影响依赖或项目外部状态",
            )
        return AuditDecision(
            requires_approval=level == AuditLevel.STRICT,
            dangerous=False,
            purpose=purpose,
            risk="在项目目录内执行终端命令",
        )

    if "filesystem:write" in tool.permissions or "skills:write" in tool.permissions:
        target = str(args.get("path") or args.get("name") or "")
        return AuditDecision(
            requires_approval=level == AuditLevel.STRICT,
            dangerous=False,
            purpose=f"在项目目录内写入：{target}",
            risk="项目内文件写入",
        )

    if "exec:skill" in tool.permissions:
        return AuditDecision(
            requires_approval=level == AuditLevel.STRICT,
            dangerous=False,
            purpose=f"执行 Skill 脚本：{args.get('skill', '')}",
            risk="执行项目内 Skill 脚本",
        )

    return AuditDecision(
        requires_approval=False,
        dangerous=False,
        purpose=f"调用工具：{tool.name}",
    )


def command_escapes_project(command: str, project_root: Any) -> bool:
    """Conservative check that a command stays inside the project folder."""
    root = str(project_root).lower()
    lowered = command.lower()
    if re.search(r"(^|\s)(?:cd|pushd|set-location|sl)\s+(\.\.|/|\\)", lowered):
        return True
    if re.search(r"(^|\s)(?:cd|pushd|set-location|sl)\s+[a-z]:\\", lowered):
        drive_path = re.search(r"(?:cd|pushd|set-location|sl)\s+([a-z]:\\)", lowered)
        if drive_path and not root.startswith(drive_path.group(1)):
            return True
    for match in re.finditer(r"[a-z]:\\[^\\\s]*", lowered):
        candidate = match.group(0)
        if not root.startswith(candidate.lower()):
            return True
    return bool(re.search(r"(^|\s)\.\.(\\|/|\s|$)", lowered))
