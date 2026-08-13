"""Task scheduler: preserves dependency order and marks async work."""

from __future__ import annotations

import re

from agent_backend.app.orchestration.models import TaskComplexity, TaskStep

_ASYNC_RE = re.compile(r"(异步|并行|同时|后台|async|parallel)", re.I)


class TaskScheduler:
    def schedule(self, steps: list[TaskStep], kind: TaskComplexity) -> list[TaskStep]:
        scheduled: list[TaskStep] = []
        for step in steps:
            dispatch = step.dispatch
            if kind in (TaskComplexity.ASYNC, TaskComplexity.COMPLEX) and _ASYNC_RE.search(
                step.description
            ):
                dispatch = "async"
            scheduled.append(
                TaskStep(
                    id=step.id,
                    title=step.title,
                    description=step.description,
                    dispatch=dispatch,
                    required_skills=list(step.required_skills),
                )
            )
        return scheduled
