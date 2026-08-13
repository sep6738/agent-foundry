"""Discover and merge project instruction files (AGENTS.md / CLAUDE.md)."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass
class InstructionFile:
    name: str
    path: str
    priority: int
    sections: dict[str, str]
    content: str


@dataclass
class InstructionBundle:
    files: list[InstructionFile] = field(default_factory=list)

    def render(self) -> str:
        parts = []
        for file in self.files:
            parts.append(f'<project_instructions path="{file.path}">')
            for name, body in file.sections.items():
                parts.append(f'<section name="{name}">\n{body.strip()}\n</section>')
            parts.append("</project_instructions>")
        return "\n".join(parts)


class InstructionLoader:
    def __init__(self, filenames: tuple[str, ...] = ("AGENTS.md", "CLAUDE.md")) -> None:
        self.filenames = filenames
        self._cache: dict[str, tuple[float, int, InstructionFile]] = {}

    def load(
        self,
        project_root: Path,
        user_home: Path | None = None,
        trusted_roots: tuple[Path, ...] = (),
    ) -> InstructionBundle:
        files: list[InstructionFile] = []
        if user_home is not None:
            for name in ("MEMORY.md", ".claude.md"):
                path = user_home / ".agent" / name
                if not path.is_file():
                    path = user_home / name
                if path.is_file():
                    files.append(self._load_file(path, priority=1))
        root = project_root.resolve()
        trusted = [path.resolve() for path in trusted_roots] if trusted_roots else [root]
        is_trusted = any(root == item or root.is_relative_to(item) for item in trusted)
        if is_trusted:
            current = root
            while True:
                for name in self.filenames:
                    for relative in ("", ".agent", ".claude"):
                        path = current / relative / name if relative else current / name
                        if path.is_file():
                            files.append(self._load_file(path))
                if current.parent == current:
                    break
                current = current.parent
        files.sort(key=lambda f: f.priority, reverse=True)
        return InstructionBundle(files=files)

    def reload(self) -> None:
        self._cache.clear()

    def _load_file(self, path: Path, priority: int | None = None) -> InstructionFile:
        stat = path.stat()
        cached = self._cache.get(str(path))
        if cached and cached[0] == stat.st_mtime and cached[1] == stat.st_size:
            return cached[2]
        instruction = self._parse(path)
        if priority is not None:
            instruction.priority = priority
        self._cache[str(path)] = (stat.st_mtime, stat.st_size, instruction)
        return instruction

    def _parse(self, path: Path) -> InstructionFile:
        content = path.read_text(encoding="utf-8")
        sections: dict[str, str] = {}
        frontmatter: dict[str, Any] = {}
        if content.startswith("---"):
            _, raw, body = content.split("---", 2)
            try:
                frontmatter = yaml.safe_load(raw) or {}
            except yaml.YAMLError:
                frontmatter = {}
            content = body
        current: str | None = None
        for line in content.splitlines():
            if line.startswith("## "):
                current = line[3:].strip()
                sections.setdefault(current, "")
            elif current and line.strip():
                sections[current] += line + "\n"
        depth = len(path.resolve().parts)
        return InstructionFile(
            name=path.name,
            path=str(path),
            priority=int(frontmatter.get("priority", depth)),
            sections=sections or {"content": content.strip()},
            content=content.strip(),
        )
