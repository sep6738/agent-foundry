"""Skill discovery, validation, editing, and invocation recording."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from sqlalchemy import select

from agent_backend.app.storage.database import Database
from agent_backend.app.storage.models import Skill as SkillRow
from agent_backend.app.storage.models import SkillInvocation, SkillVersion, new_id

_NAME_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_-]*$")
_MAX_SKILL_BYTES = 64_000


@dataclass
class SkillMeta:
    name: str
    description: str
    when: str = ""
    version: str = "1.0.0"
    source_path: str = ""
    scope: str = "project"
    disabled: bool = False


@dataclass
class Skill:
    meta: SkillMeta
    content: str


class SkillRegistry:
    def __init__(
        self,
        db: Database,
        dirs: tuple[str, ...] = (".agent/skills", ".claude/skills"),
    ) -> None:
        self.db = db
        self.dirs = dirs
        self.builtin_dir = Path(__file__).resolve().parent / "builtin"

    def list_skills(self, project_root: Path, user_home: Path | None = None) -> list[SkillMeta]:
        found: dict[str, SkillMeta] = {}

        def scan(directory: Path, weight: int) -> None:
            if not directory.is_dir():
                return
            for skill_file in sorted(directory.glob("*/SKILL.md")):
                meta = self._parse_meta(skill_file)
                if meta.disabled:
                    continue
                existing = found.get(meta.name)
                if existing is None or weight > self._priority(existing.scope):
                    meta.scope = _scope_for_weight(weight)
                    found[meta.name] = meta

        scan(self.builtin_dir, 1)
        if user_home is not None:
            scan(user_home / ".agent" / "skills", 2)
        for relative in self.dirs:
            scan((project_root / relative).resolve(), 3)

        with self.db.session() as session:
            for row in session.scalars(select(SkillRow).where(SkillRow.status == "active")):
                found.setdefault(
                    row.name,
                    SkillMeta(
                        name=row.name,
                        description=row.description,
                        source_path=row.source_path,
                        scope=row.scope,
                    ),
                )
        return sorted(found.values(), key=lambda meta: (meta.scope, meta.name))

    def get_skill(
        self,
        name: str,
        project_root: Path,
        user_home: Path | None = None,
    ) -> Skill | None:
        for meta in self.list_skills(project_root, user_home=user_home):
            if meta.name != name:
                continue
            if not meta.source_path:
                continue
            path = Path(meta.source_path)
            if path.is_file():
                return Skill(meta=meta, content=path.read_text(encoding="utf-8"))
        return None

    def validate(self, content: str) -> dict[str, Any]:
        errors: list[str] = []
        if len(content.encode("utf-8")) > _MAX_SKILL_BYTES:
            errors.append("skill exceeds 64KB")
        if not content.startswith("---"):
            errors.append("skill must start with YAML frontmatter")
        meta: dict[str, Any] = {}
        try:
            _, raw, _ = content.split("---", 2)
            parsed = yaml.safe_load(raw) or {}
            meta = parsed if isinstance(parsed, dict) else {}
        except (ValueError, yaml.YAMLError):
            errors.append("invalid frontmatter")
        for required in ("name", "description"):
            if not meta.get(required):
                errors.append(f"missing frontmatter field: {required}")
        name = str(meta.get("name", ""))
        if name and not _NAME_RE.match(name):
            errors.append("name must match [a-zA-Z0-9][a-zA-Z0-9_-]*")
        return {"ok": not errors, "errors": errors, "meta": meta}

    def save(
        self,
        name: str,
        content: str,
        project_root: Path,
        scope: str = "project",
        user_home: Path | None = None,
    ) -> Skill:
        validation = self.validate(content)
        if not validation["ok"]:
            raise ValueError("; ".join(validation["errors"]))
        meta = validation["meta"]
        name = str(meta.get("name") or name)
        if scope == "user":
            base = (user_home or Path.home()) / ".agent" / "skills"
        else:
            base = project_root / self.dirs[0]
        directory = (base / name).resolve()
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / "SKILL.md"
        path.write_text(content, encoding="utf-8")
        with self.db.transaction() as session:
            row = session.scalar(select(SkillRow).where(SkillRow.name == name))
            if row is None:
                row = SkillRow(
                    id=new_id("skl"),
                    name=name,
                    description=str(meta.get("description", "")),
                    source_path=str(path),
                    scope=scope,
                    version=1,
                )
                session.add(row)
            else:
                row.description = str(meta.get("description", ""))
                row.source_path = str(path)
                row.scope = scope
                row.status = "active"
                row.version += 1
            session.add(
                SkillVersion(
                    id=new_id("skv"),
                    skill_id=row.id,
                    version=row.version,
                    content=content,
                )
            )
            session.flush()
        return Skill(
            meta=SkillMeta(
                name=name,
                description=str(meta.get("description", "")),
                when=str(meta.get("when", "")),
                version=str(meta.get("version", "1.0.0")),
                source_path=str(path),
                scope=scope,
            ),
            content=content,
        )

    def delete(self, name: str, project_root: Path, user_home: Path | None = None) -> bool:
        deleted = False
        with self.db.transaction() as session:
            row = session.scalar(select(SkillRow).where(SkillRow.name == name))
            if row is not None:
                row.status = "disabled"
                deleted = True
        directories = [project_root / d for d in self.dirs]
        if user_home is not None:
            directories.append(user_home / ".agent" / "skills")
        for directory in directories:
            if directory is None:
                continue
            target = (directory / name / "SKILL.md").resolve()
            if target.is_file() and target.is_relative_to(project_root.resolve()):
                target.unlink(missing_ok=True)
                deleted = True
        return deleted

    def record_invocation(
        self,
        *,
        session_id: str,
        skill_name: str,
        mode: str,
        result: str,
        duration_ms: int,
    ) -> None:
        with self.db.transaction() as session:
            row = session.scalar(select(SkillRow).where(SkillRow.name == skill_name))
            session.add(
                SkillInvocation(
                    id=new_id("siv"),
                    session_id=session_id,
                    skill_id=row.id if row else None,
                    mode=mode,
                    result=result,
                    duration_ms=duration_ms,
                )
            )

    @staticmethod
    def _priority(scope: str) -> int:
        return {"project": 3, "user": 2, "builtin": 1}.get(scope, 2)

    @staticmethod
    def _parse_meta(path: Path) -> SkillMeta:
        content = path.read_text(encoding="utf-8")
        meta: dict[str, Any] = {}
        if content.startswith("---"):
            try:
                _, raw, _ = content.split("---", 2)
                parsed = yaml.safe_load(raw) or {}
                meta = parsed if isinstance(parsed, dict) else {}
            except (ValueError, yaml.YAMLError):
                meta = {}
        return SkillMeta(
            name=str(meta.get("name", path.parent.name)),
            description=str(meta.get("description", "")),
            when=str(meta.get("when", "")),
            version=str(meta.get("version", "1.0.0")),
            source_path=str(path),
            scope=str(meta.get("scope", "project")),
            disabled=bool(meta.get("disabled", False)),
        )


def _scope_for_weight(weight: int) -> str:
    return {1: "builtin", 2: "user", 3: "project"}[weight]
