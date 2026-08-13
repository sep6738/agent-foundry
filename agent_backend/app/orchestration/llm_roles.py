"""Model-backed planner, scheduler, and HR recruiter roles."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from agent_backend.app.core.context import RuntimeContext
from agent_backend.app.orchestration.classifier import ComplexityClassifier
from agent_backend.app.orchestration.models import AgentSpec, TaskComplexity, TaskStep
from agent_backend.app.orchestration.planner import RequirementAnalyzer
from agent_backend.app.orchestration.recruiter import SkillRecruiter
from agent_backend.app.orchestration.role_agent import RoleAgent, parse_json_object
from agent_backend.app.orchestration.scheduler import TaskScheduler


class LLMPlanner:
    def __init__(self, context: RuntimeContext) -> None:
        self.role_agent = RoleAgent(context)
        self.classifier = ComplexityClassifier()
        self.rule_planner = RequirementAnalyzer(self.classifier)

    def plan(self, text: str, kind: TaskComplexity) -> list[TaskStep]:
        prompt = (
            "你是需求分析 Agent。请把用户任务拆成有序子任务，并只输出 JSON。"
            '格式：{"steps":[{"id":"step_0","title":"...",'
            '"description":"...","dispatch":"sync或async"}]}。'
            f"任务：{text}"
        )
        return self.role_agent.run(
            prompt,
            lambda raw: _parse_steps(raw),
            lambda: self.rule_planner.analyze(text),
        )


class LLMScheduler:
    def __init__(self, context: RuntimeContext) -> None:
        self.role_agent = RoleAgent(context)
        self.rule_scheduler = TaskScheduler()

    def schedule(self, steps: list[TaskStep], kind: TaskComplexity) -> list[TaskStep]:
        prompt = (
            "你是排期与任务分配 Agent。请保留子任务顺序并标注同步或异步，只输出 JSON。"
            '格式：{"steps":[{"id":"...","dispatch":"sync或async"}]}。'
            f"任务模式：{kind.value}\n子任务：{_steps_to_json(steps)}"
        )

        def parser(raw: str) -> list[TaskStep] | None:
            data = parse_json_object(raw)
            return _merge_steps(steps, data)

        return self.role_agent.run(
            prompt,
            parser,
            lambda: self.rule_scheduler.schedule(steps, kind),
        )


class LLMRecruiter:
    def __init__(self, context: RuntimeContext) -> None:
        self.role_agent = RoleAgent(context)
        self.rule_recruiter = SkillRecruiter(context.skill_registry)

    def recruit(
        self,
        steps: list[TaskStep],
        project_root: Path,
        user_home: Path | None = None,
    ) -> list[AgentSpec]:
        skills = self.rule_recruiter.registry.list_skills(project_root, user_home=user_home)
        skill_lines = "\n".join(
            f"- {skill.name}: {skill.description} (when: {skill.when})" for skill in skills
        )
        prompt = (
            "你是 HR 招募 Agent。请根据子任务类型，把合适的用户 Skill 分配给每个员工 Agent，"
            '只输出 JSON。格式：{"agents":[{"name":"employee-0","role":"...",'
            '"skills":["skill-name"]}]}。\n可用 Skill：\n'
            f"{skill_lines or '（无）'}\n子任务：{_steps_to_json(steps)}"
        )

        def parser(raw: str) -> list[AgentSpec] | None:
            data = parse_json_object(raw)
            if not data:
                return None
            raw_agents = data.get("agents")
            if not isinstance(raw_agents, list):
                return None
            agents: list[AgentSpec] = []
            for index, item in enumerate(raw_agents):
                if not isinstance(item, dict):
                    continue
                name = str(item.get("name") or f"employee-{index}")
                role = str(item.get("role") or f"执行员工 {index + 1}")
                skill_values = item.get("skills") or []
                skill_list = [str(skill) for skill in skill_values if isinstance(skill, str)]
                agents.append(AgentSpec(name=name, role=role, instructions="", skills=skill_list))
            return agents if agents else None

        return self.role_agent.run(
            prompt,
            parser,
            lambda: self.rule_recruiter.recruit(steps, project_root, user_home=user_home),
        )


def _parse_steps(raw: str) -> list[TaskStep] | None:
    data = parse_json_object(raw)
    if not data or not isinstance(data.get("steps"), list):
        return None
    steps: list[TaskStep] = []
    for index, item in enumerate(data["steps"]):
        if not isinstance(item, dict):
            continue
        dispatch = str(item.get("dispatch", "sync"))
        if dispatch not in {"sync", "async"}:
            dispatch = "sync"
        steps.append(
            TaskStep(
                id=str(item.get("id") or f"step_{index}"),
                title=str(item.get("title") or f"步骤 {index + 1}"),
                description=str(item.get("description") or ""),
                dispatch=dispatch,
                required_skills=[
                    str(skill) for skill in (item.get("skills") or []) if isinstance(skill, str)
                ],
            )
        )
    return steps or None


def _merge_steps(steps: list[TaskStep], data: dict[str, Any] | None) -> list[TaskStep] | None:
    if not data or not isinstance(data.get("steps"), list):
        return None
    by_id = {str(item.get("id")): item for item in data["steps"] if isinstance(item, dict)}
    merged: list[TaskStep] = []
    for step in steps:
        item = by_id.get(step.id, {})
        dispatch = str(item.get("dispatch", step.dispatch))
        if dispatch not in {"sync", "async"}:
            dispatch = step.dispatch
        merged.append(
            TaskStep(
                id=step.id,
                title=step.title,
                description=step.description,
                dispatch=dispatch,
                required_skills=list(step.required_skills),
            )
        )
    return merged


def _steps_to_json(steps: list[TaskStep]) -> str:
    import json

    return json.dumps(
        [
            {
                "id": step.id,
                "title": step.title,
                "description": step.description,
                "dispatch": step.dispatch,
            }
            for step in steps
        ],
        ensure_ascii=False,
    )
