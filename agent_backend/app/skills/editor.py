"""Skill editing facade used by the API and the edit_skill tool."""

from __future__ import annotations

from pathlib import Path

from agent_backend.app.skills.registry import Skill, SkillRegistry


class SkillEditor:
    def __init__(self, registry: SkillRegistry) -> None:
        self.registry = registry

    def create_or_update(
        self,
        name: str,
        content: str,
        project_root: Path,
        scope: str = "project",
        user_home: Path | None = None,
    ) -> Skill:
        return self.registry.save(name, content, project_root, scope, user_home=user_home)

    def delete(
        self,
        name: str,
        project_root: Path,
        user_home: Path | None = None,
    ) -> bool:
        return self.registry.delete(name, project_root, user_home=user_home)

    def validate(self, content: str) -> dict:
        return self.registry.validate(content)
