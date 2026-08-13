"""Shared data structures for multi-agent orchestration."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class TaskComplexity(StrEnum):
    SIMPLE = "simple"
    ASYNC = "async"
    COMPLEX = "complex"


@dataclass
class TaskStep:
    id: str
    title: str
    description: str
    dispatch: str = "sync"
    required_skills: list[str] = field(default_factory=list)


@dataclass
class AgentSpec:
    name: str
    role: str
    instructions: str
    skills: list[str] = field(default_factory=list)


@dataclass
class TaskPlan:
    kind: TaskComplexity
    steps: list[TaskStep] = field(default_factory=list)
    agents: list[AgentSpec] = field(default_factory=list)
    source: str = "rule"


@dataclass
class AgentResult:
    step_id: str
    agent_name: str
    response: str
    ok: bool
    error: str | None = None
    session_id: str | None = None
