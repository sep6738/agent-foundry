"""Shared pytest fixtures."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_backend.app import create_app
from agent_backend.app.config import Settings
from agent_backend.app.storage.database import Database


@pytest.fixture()
def settings(tmp_path: Path) -> Settings:
    db_path = tmp_path / "test.db"
    return Settings(
        app_env="test",
        database_url=f"sqlite:///{db_path}",
        model_provider="stub",
        project_root=Path(__file__).resolve().parent.parent,
    )


@pytest.fixture()
def db(settings: Settings) -> Database:
    database = Database(settings.database_url)
    database.init()
    yield database
    database.dispose()


@pytest.fixture()
def app(settings: Settings):
    app = create_app(settings)
    app.config["TESTING"] = True
    yield app
