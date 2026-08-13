"""Project folder management tests."""

from __future__ import annotations

from pathlib import Path

from agent_backend.app import create_app
from agent_backend.app.config import Settings
from agent_backend.app.core.context import RuntimeContext
from agent_backend.app.core.runtime import AgentRuntime
from agent_backend.app.projects.manager import ProjectManager
from agent_backend.app.storage.database import Database


def test_project_manager_crud(db: Database, tmp_path: Path) -> None:
    manager = ProjectManager(db)
    project = manager.create("u1", "demo", str(tmp_path))
    assert manager.get(project.id) is not None
    assert any(item.id == project.id for item in manager.list("u1"))
    assert manager.delete(project.id)
    assert manager.get(project.id) is None


def test_project_manager_rejects_dangerous_roots(db: Database, tmp_path: Path) -> None:
    manager = ProjectManager(db)
    try:
        manager.create("u1", "root", str(Path(tmp_path.anchor)))
    except ValueError as exc:
        assert "filesystem root" in str(exc)
    else:
        raise AssertionError("filesystem root should be rejected")
    try:
        manager.create("u1", "home", str(Path.home()))
    except ValueError as exc:
        assert "home directory" in str(exc)
    else:
        raise AssertionError("home directory should be rejected")


def test_deleted_project_does_not_fall_back(db: Database, tmp_path: Path) -> None:
    manager = ProjectManager(db)
    project = manager.create("u1", "demo", str(tmp_path))
    assert manager.delete(project.id)
    try:
        manager.resolve_path(project.id, tmp_path / "fallback")
    except ValueError as exc:
        assert "project not found" in str(exc)
    else:
        raise AssertionError("deleted project must not fall back to global root")


def test_session_bound_to_project_uses_project_root(tmp_path: Path) -> None:
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    (project_dir / "marker.txt").write_text("marker", encoding="utf-8")
    fallback = tmp_path / "fallback"
    fallback.mkdir()

    db = Database(f"sqlite:///{tmp_path / 'project.db'}")
    db.init()
    settings = Settings(
        app_env="test",
        database_url=db.url,
        model_provider="stub",
        project_root=fallback,
    )
    context = RuntimeContext.from_settings(settings, db)
    project = context.project_manager.create("u1", "project", str(project_dir))
    session = context.session_manager.create("u1", "bound", project_id=project.id)
    result = AgentRuntime(context).run_turn(
        session_id=session.id,
        user_id="u1",
        text="list directory",
        thread_id=session.thread_id,
    )
    assert "marker.txt" in result["response"]


def test_project_api_registers_folder_and_session(tmp_path: Path) -> None:
    project_dir = tmp_path / "site"
    project_dir.mkdir()
    settings = Settings(
        app_env="test",
        database_url=f"sqlite:///{tmp_path / 'api.db'}",
        model_provider="stub",
        project_root=tmp_path,
    )
    client = create_app(settings).test_client()
    created = client.post(
        "/v1/projects",
        json={"user_id": "u1", "name": "site", "path": str(project_dir)},
    )
    assert created.status_code == 201
    project_id = created.get_json()["id"]
    session = client.post(
        "/v1/sessions",
        json={"user_id": "u1", "project_id": project_id},
    )
    assert session.status_code == 201
    assert session.get_json()["project_id"] == project_id
    assert client.get(f"/v1/projects/{project_id}").status_code == 200
    assert client.delete(f"/v1/projects/{project_id}").status_code == 200
