"""Synchronous and asynchronous employee-agent execution."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed

from agent_backend.app.core.context import RuntimeContext
from agent_backend.app.core.runtime import AgentRuntime
from agent_backend.app.orchestration.models import AgentResult, AgentSpec, TaskPlan, TaskStep
from agent_backend.app.storage.models import Session


class SubAgentExecutor:
    def __init__(self, context: RuntimeContext, trace_id: str | None = None) -> None:
        self.context = context
        self.trace_id = trace_id

    def execute(self, plan: TaskPlan, parent_session: Session, user_id: str) -> list[AgentResult]:
        sync_steps = [step for step in plan.steps if step.dispatch != "async"]
        async_steps = [step for step in plan.steps if step.dispatch == "async"]

        results: list[AgentResult] = []
        for step in sync_steps:
            agent = self._agent_for(plan, step)
            results.append(self._run_step(step, agent, parent_session, user_id))

        if async_steps:
            with ThreadPoolExecutor(max_workers=len(async_steps)) as pool:
                futures = {
                    pool.submit(
                        self._run_step,
                        step,
                        self._agent_for(plan, step),
                        parent_session,
                        user_id,
                    ): step
                    for step in async_steps
                }
                for future in as_completed(futures):
                    results.append(future.result())

        order = {step.id: index for index, step in enumerate(plan.steps)}
        results.sort(key=lambda item: order.get(item.step_id, 0))
        return results

    def _agent_for(self, plan: TaskPlan, step: TaskStep) -> AgentSpec:
        for index, item in enumerate(plan.steps):
            if item.id == step.id and index < len(plan.agents):
                return plan.agents[index]
        return AgentSpec(name=step.id, role=step.title, instructions=step.description)

    def _run_step(
        self,
        step: TaskStep,
        agent: AgentSpec,
        parent_session: Session,
        user_id: str,
    ) -> AgentResult:
        manager = self.context.session_manager
        sub_session = manager.create(
            user_id,
            title=f"subagent:{agent.name}",
            project_id=parent_session.project_id,
        )
        for skill_name in agent.skills:
            skill = self.context.skill_registry.get_skill(
                skill_name,
                self.context.settings.project_root,
                user_home=self.context.user_home,
            )
            if skill is not None:
                manager.append_entry(
                    sub_session.id,
                    "session_instruction",
                    {"key": f"employee-skill:{skill_name}", "content": skill.content},
                )
        runtime = AgentRuntime(self.context)
        result = runtime.run_turn(
            session_id=sub_session.id,
            user_id=user_id,
            text=step.description,
            thread_id=sub_session.thread_id,
            trace_id=self.trace_id,
        )
        if result.get("error"):
            return AgentResult(
                step_id=step.id,
                agent_name=agent.name,
                response="",
                ok=False,
                error=result["error"],
                session_id=sub_session.id,
            )
        return AgentResult(
            step_id=step.id,
            agent_name=agent.name,
            response=result.get("response", ""),
            ok=result.get("status") != "aborted",
            session_id=sub_session.id,
        )
