"""HR recruiter: maps user skills to employee agents by task type."""

from __future__ import annotations

import re
from pathlib import Path

from agent_backend.app.orchestration.models import AgentSpec, TaskStep
from agent_backend.app.skills.registry import SkillRegistry

_TOKEN_RE = re.compile(r"[a-zA-Z0-9_]+|[\u4e00-\u9fff]+", re.UNICODE)


class SkillRecruiter:
    def __init__(self, registry: SkillRegistry) -> None:
        self.registry = registry

    def recruit(
        self,
        steps: list[TaskStep],
        project_root: Path,
        user_home: Path | None = None,
    ) -> list[AgentSpec]:
        skills = self.registry.list_skills(project_root, user_home=user_home)
        agents: list[AgentSpec] = []
        for index, step in enumerate(steps):
            tokens = _TOKEN_RE.findall(step.title + " " + step.description)
            matched = [
                skill.name
                for skill in skills
                if any(
                    token.lower() in skill.name.lower()
                    or token in skill.description
                    or token in skill.when
                    for token in tokens
                )
            ]
            agents.append(
                AgentSpec(
                    name=f"employee-{index}",
                    role=f"执行员工 {index + 1}",
                    instructions=step.description,
                    skills=matched,
                )
            )
        return agents
