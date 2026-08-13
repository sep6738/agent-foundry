"""Skill registry tests."""

from __future__ import annotations

from pathlib import Path

from agent_backend.app.skills.editor import SkillEditor
from agent_backend.app.skills.registry import SkillRegistry
from agent_backend.app.skills.runner import SkillRunner
from agent_backend.app.storage.database import Database


def test_validate_and_save_skill(db: Database, tmp_path: Path) -> None:
    registry = SkillRegistry(db, (".agent/skills",))
    content = (
        "---\nname: refactor-python\ndescription: 重构 Python 代码时使用\n"
        "when: 用户要求重构\nversion: 1.0.0\n---\n\n## Steps\n1. 先阅读代码\n"
    )
    assert registry.validate(content)["ok"]
    skill = registry.save("refactor-python", content, tmp_path)
    assert skill.meta.name == "refactor-python"
    metas = registry.list_skills(tmp_path)
    assert any(meta.name == "refactor-python" for meta in metas)


def test_delete_skill_disables_and_removes_file(db: Database, tmp_path: Path) -> None:
    registry = SkillRegistry(db, (".agent/skills",))
    content = "---\nname: obsolete-skill\ndescription: old skill\n---\n\n## Steps\n1. Old step.\n"
    registry.save("obsolete-skill", content, tmp_path)
    assert registry.delete("obsolete-skill", tmp_path)
    assert registry.get_skill("obsolete-skill", tmp_path) is None
    assert all(meta.name != "obsolete-skill" for meta in registry.list_skills(tmp_path))


def test_validate_rejects_bad_name(db: Database, tmp_path: Path) -> None:
    registry = SkillRegistry(db, (".agent/skills",))
    content = "---\nname: bad name!\ndescription: invalid\n---\n\n## Steps\n1. Do something.\n"
    validation = registry.validate(content)
    assert validation["ok"] is False


def test_skill_editor_and_runner_execute_script(db: Database, tmp_path: Path) -> None:
    registry = SkillRegistry(db, (".agent/skills",))
    editor = SkillEditor(registry)
    content = (
        "---\nname: script-skill\ndescription: has a script\n---\n\n## Steps\n1. Run verify.py.\n"
    )
    editor.create_or_update("script-skill", content, tmp_path)
    scripts = tmp_path / ".agent" / "skills" / "script-skill" / "scripts"
    scripts.mkdir(parents=True)
    (scripts / "verify.py").write_text('print("script-ok")\n', encoding="utf-8")
    skill = registry.get_skill("script-skill", tmp_path)
    assert skill is not None
    result = SkillRunner().run_script(skill, "verify.py")
    assert result["ok"] is True
    assert "script-ok" in result["output"]
