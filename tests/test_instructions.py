"""Instruction discovery and injection tests."""

from __future__ import annotations

from pathlib import Path

from agent_backend.app.instructions.injector import PromptInjector
from agent_backend.app.instructions.loader import InstructionLoader


def test_loader_finds_agents_md_and_parses_sections(tmp_path: Path) -> None:
    (tmp_path / "AGENTS.md").write_text(
        "---\nname: project-guide\npriority: 10\n---\n## 约束\n- 测试命令为 pytest\n",
        encoding="utf-8",
    )
    bundle = InstructionLoader().load(tmp_path)
    own = next(file for file in bundle.files if file.path.startswith(str(tmp_path)))
    assert own.priority == 10
    assert "pytest" in own.content


def test_loader_finds_nested_instruction_directories(tmp_path: Path) -> None:
    (tmp_path / "AGENTS.md").write_text(
        "---\npriority: 5\n---\n## 约束\n- 全局规则\n",
        encoding="utf-8",
    )
    nested = tmp_path / ".agent"
    nested.mkdir()
    (nested / "AGENTS.md").write_text(
        "---\npriority: 9\n---\n## 约束\n- 深层规则\n",
        encoding="utf-8",
    )
    bundle = InstructionLoader().load(tmp_path)
    assert any("深层规则" in file.content for file in bundle.files)
    assert bundle.files[0].priority == 9


def test_prompt_injector_respects_budget_without_mutation(tmp_path: Path) -> None:
    (tmp_path / "AGENTS.md").write_text(
        "---\npriority: 10\n---\n## 约束\n" + ("- 很长的规则内容" * 30),
        encoding="utf-8",
    )
    bundle = InstructionLoader().load(tmp_path)
    rendered = PromptInjector.inject(bundle, budget_tokens=10)
    assert len(rendered) <= 40
    assert bundle.files[0].sections["约束"]
