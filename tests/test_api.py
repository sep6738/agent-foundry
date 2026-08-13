"""Flask API integration tests."""

from __future__ import annotations

from pathlib import Path

from flask import Flask

from agent_backend.app import create_app
from agent_backend.app.config import Settings


def test_health(app: Flask) -> None:
    response = app.test_client().get("/health")
    assert response.status_code == 200
    assert response.get_json()["status"] == "ok"


def test_session_and_sse_flow(app: Flask) -> None:
    client = app.test_client()
    created = client.post("/v1/sessions", json={"user_id": "u1", "title": "demo"})
    assert created.status_code == 201
    session_id = created.get_json()["id"]
    response = client.post(
        f"/v1/sessions/{session_id}/messages",
        json={"message": "hello"},
    )
    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "instruction_loaded" in body
    assert "turn_finished" in body
    history = client.get(f"/v1/sessions/{session_id}/history")
    assert history.status_code == 200
    assert len(history.get_json()["entries"]) >= 2


def test_memory_api_roundtrip(app: Flask) -> None:
    client = app.test_client()
    created = client.post(
        "/v1/memories",
        json={"user_id": "u1", "subject": "editor", "content": "prefers vim"},
    )
    assert created.status_code == 201
    memory_id = created.get_json()["id"]
    found = client.get("/v1/memories", query_string={"q": "vim", "user_id": "u1"})
    assert found.status_code == 200
    assert any(fact["id"] == memory_id for fact in found.get_json()["facts"])
    deleted = client.delete(f"/v1/memories/{memory_id}")
    assert deleted.status_code == 200


def test_skill_api_validation(app: Flask) -> None:
    client = app.test_client()
    response = client.post("/v1/skills/refactor/validate", json={"content": "not frontmatter"})
    assert response.status_code == 200
    assert response.get_json()["ok"] is False


def test_session_instruction_lifecycle(app: Flask) -> None:
    client = app.test_client()
    session_id = client.post("/v1/sessions", json={"user_id": "u1"}).get_json()["id"]
    injected = client.post(
        f"/v1/sessions/{session_id}/instructions",
        json={"key": "rule-1", "content": "必须使用 pytest"},
    )
    assert injected.status_code == 201
    listed = client.get(f"/v1/sessions/{session_id}/instructions").get_json()
    assert any(item["key"] == "rule-1" for item in listed["instructions"])
    removed = client.delete(f"/v1/sessions/{session_id}/instructions/rule-1")
    assert removed.status_code == 200
    listed = client.get(f"/v1/sessions/{session_id}/instructions").get_json()
    assert listed["instructions"] == []


def test_sessions_list_get_and_delete(app: Flask) -> None:
    client = app.test_client()
    created = client.post("/v1/sessions", json={"user_id": "u1", "title": "one"}).get_json()
    session_id = created["id"]
    assert client.get("/v1/sessions", query_string={"user_id": "u1"}).get_json()["sessions"]
    assert client.get(f"/v1/sessions/{session_id}").status_code == 200
    assert client.delete(f"/v1/sessions/{session_id}").status_code == 200
    assert client.get(f"/v1/sessions/{session_id}").status_code == 404


def test_compact_and_metrics(app: Flask) -> None:
    client = app.test_client()
    session_id = client.post("/v1/sessions", json={"user_id": "u1"}).get_json()["id"]
    client.post(f"/v1/sessions/{session_id}/messages", json={"message": "hello"})
    compact = client.post(f"/v1/sessions/{session_id}/compact")
    assert compact.status_code == 200
    assert "result" in compact.get_json()
    metrics = client.get("/metrics").get_json()
    assert metrics["sessions"] >= 1
    assert metrics["tool_calls"] >= 0


def test_skill_api_get_update_use_delete(tmp_path: Path) -> None:
    settings = Settings(
        app_env="test",
        database_url=f"sqlite:///{tmp_path / 'api.db'}",
        model_provider="stub",
        project_root=tmp_path,
    )
    client = create_app(settings).test_client()
    content = "---\nname: api-skill\ndescription: api skill\n---\n\n## Steps\n1. Do it.\n"
    created = client.post("/v1/skills", json={"name": "api-skill", "content": content})
    assert created.status_code == 201
    fetched = client.get("/v1/skills/api-skill")
    assert fetched.status_code == 200
    assert fetched.get_json()["content"].startswith("---")
    session_id = client.post("/v1/sessions", json={"user_id": "u1"}).get_json()["id"]
    used = client.post("/v1/skills/api-skill/use", json={"session_id": session_id})
    assert used.status_code == 201
    instructions = client.get(f"/v1/sessions/{session_id}/instructions").get_json()
    assert any(item["key"] == "skill:api-skill" for item in instructions["instructions"])
    assert client.delete("/v1/skills/api-skill").status_code == 200
    assert client.get("/v1/skills/api-skill").status_code == 404


def test_api_key_auth(tmp_path: Path) -> None:
    settings = Settings(
        app_env="test",
        database_url=f"sqlite:///{tmp_path / 'auth.db'}",
        api_keys=("secret-key",),
    )
    client = create_app(settings).test_client()
    assert client.get("/health").status_code == 401
    ok = client.get("/health", headers={"X-API-Key": "secret-key"})
    assert ok.status_code == 200


def test_api_key_maps_to_tenant_user(tmp_path: Path) -> None:
    settings = Settings(
        app_env="test",
        database_url=f"sqlite:///{tmp_path / 'auth2.db'}",
        api_keys=("secret-key",),
        api_key_users={"secret-key": "mapped-user"},
    )
    client = create_app(settings).test_client()
    created = client.post(
        "/v1/sessions",
        json={"title": "tenant"},
        headers={"X-API-Key": "secret-key"},
    )
    assert created.status_code == 201
    assert created.get_json()["user_id"] == "mapped-user"
