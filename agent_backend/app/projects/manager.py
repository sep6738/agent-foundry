"""Project folder registration and resolution."""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import select

from agent_backend.app.storage.database import Database
from agent_backend.app.storage.models import Project, User, new_id


class ProjectManager:
    def __init__(self, db: Database) -> None:
        self.db = db

    def create(self, user_id: str, name: str, path: str) -> Project:
        resolved = Path(path).expanduser().resolve()
        if not resolved.is_dir():
            raise ValueError(f"not a directory: {resolved}")
        self._validate_root(resolved)
        with self.db.transaction() as session:
            user = session.execute(select(User).where(User.id == user_id)).scalars().first()
            if user is None:
                user = User(id=user_id, name=user_id)
                session.add(user)
            existing = (
                session.execute(select(Project).where(Project.path == str(resolved)))
                .scalars()
                .first()
            )
            if existing is not None:
                raise ValueError("project path already registered")
            row = Project(
                id=new_id("prj"),
                user_id=user_id,
                name=name or resolved.name,
                path=str(resolved),
            )
            session.add(row)
            session.flush()
            return row

    def list(self, user_id: str | None = None) -> list[Project]:
        with self.db.session() as session:
            query = select(Project).order_by(Project.updated_at.desc())
            if user_id:
                query = query.where(Project.user_id == user_id)
            return list(session.scalars(query))

    def get(self, project_id: str) -> Project | None:
        with self.db.session() as session:
            row = session.get(Project, project_id)
            return row if row is not None and row.status != "deleted" else None

    def delete(self, project_id: str) -> bool:
        with self.db.transaction() as session:
            row = session.get(Project, project_id)
            if row is None:
                return False
            row.status = "deleted"
            return True

    def resolve_path(self, project_id: str | None, fallback: Path) -> Path:
        if project_id is None:
            return fallback.resolve()
        project = self.get(project_id)
        if project is None:
            raise ValueError("project not found")
        return Path(project.path).resolve()

    @staticmethod
    def _validate_root(resolved: Path) -> None:
        if resolved == Path(resolved.anchor):
            raise ValueError("cannot use filesystem root as project folder")
        if resolved == Path.home().resolve():
            raise ValueError("cannot use home directory as project folder")
        blocked = {
            "windows",
            "program files",
            "program files (x86)",
            "etc",
            "usr",
            "bin",
            "root",
        }
        if resolved.name.lower() in blocked:
            raise ValueError(f"cannot use system directory as project folder: {resolved}")
