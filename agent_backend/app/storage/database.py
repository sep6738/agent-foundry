"""SQLAlchemy engine, session factory, and FTS5 bootstrap."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import Session, scoped_session, sessionmaker

from agent_backend.app.storage.models import Base


class Database:
    """Owns the engine and session factory for one SQLite database."""

    def __init__(self, url: str) -> None:
        self.url = url
        self._ensure_sqlite_directory(url)
        self.engine: Engine = create_engine(url, connect_args={"check_same_thread": False})
        self._session_factory = scoped_session(
            sessionmaker(bind=self.engine, expire_on_commit=False)
        )

    @staticmethod
    def _ensure_sqlite_directory(url: str) -> None:
        if url.startswith("sqlite:///"):
            path = url.removeprefix("sqlite:///")
            if path and path != ":memory:":
                Path(path).parent.mkdir(parents=True, exist_ok=True)

    def init(self) -> None:
        Base.metadata.create_all(self.engine)
        self._setup_fts()

    def _setup_fts(self) -> None:
        with self.engine.begin() as conn:
            conn.execute(
                text(
                    """
                    CREATE VIRTUAL TABLE IF NOT EXISTS memory_facts_fts
                    USING fts5(id UNINDEXED, subject, content, tags, keywords)
                    """
                )
            )
            conn.execute(
                text(
                    """
                    CREATE VIRTUAL TABLE IF NOT EXISTS skills_fts
                    USING fts5(id UNINDEXED, name, description, content)
                    """
                )
            )
            conn.execute(
                text(
                    """
                    CREATE TRIGGER IF NOT EXISTS memory_facts_fts_insert
                    AFTER INSERT ON memory_facts
                    BEGIN
                        INSERT INTO memory_facts_fts(id, subject, content, tags, keywords)
                        VALUES (new.id, new.subject, new.content, new.tags, new.keywords);
                    END
                    """
                )
            )
            conn.execute(
                text(
                    """
                    CREATE TRIGGER IF NOT EXISTS memory_facts_fts_update
                    AFTER UPDATE ON memory_facts
                    BEGIN
                        DELETE FROM memory_facts_fts WHERE id = old.id;
                        INSERT INTO memory_facts_fts(id, subject, content, tags, keywords)
                        VALUES (new.id, new.subject, new.content, new.tags, new.keywords);
                    END
                    """
                )
            )
            conn.execute(
                text(
                    """
                    CREATE TRIGGER IF NOT EXISTS memory_facts_fts_delete
                    AFTER DELETE ON memory_facts
                    BEGIN
                        DELETE FROM memory_facts_fts WHERE id = old.id;
                    END
                    """
                )
            )
            conn.execute(
                text(
                    """
                    CREATE TRIGGER IF NOT EXISTS skills_fts_insert
                    AFTER INSERT ON skills
                    BEGIN
                        INSERT INTO skills_fts(id, name, description, content)
                        VALUES (new.id, new.name, new.description, '');
                    END
                    """
                )
            )
            conn.execute(
                text(
                    """
                    CREATE TRIGGER IF NOT EXISTS skills_fts_update
                    AFTER UPDATE ON skills
                    BEGIN
                        DELETE FROM skills_fts WHERE id = old.id;
                        INSERT INTO skills_fts(id, name, description, content)
                        VALUES (new.id, new.name, new.description, '');
                    END
                    """
                )
            )
            conn.execute(
                text(
                    """
                    CREATE TRIGGER IF NOT EXISTS skills_fts_delete
                    AFTER DELETE ON skills
                    BEGIN
                        DELETE FROM skills_fts WHERE id = old.id;
                    END
                    """
                )
            )

    def session(self) -> Session:
        return self._session_factory()

    @contextmanager
    def transaction(self) -> Iterator[Session]:
        session = self._session_factory()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def dispose(self) -> None:
        self.engine.dispose()
