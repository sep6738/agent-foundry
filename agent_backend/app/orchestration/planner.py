"""Requirement analysis and decomposition into task steps."""

from __future__ import annotations

import re

from agent_backend.app.orchestration.classifier import ComplexityClassifier
from agent_backend.app.orchestration.models import TaskComplexity, TaskStep

_SPLIT_RE = re.compile(r"[。！？\n;；]+")
_ASYNC_RE = re.compile(r"(异步|并行|同时|后台|async|parallel)", re.I)


class RequirementAnalyzer:
    def __init__(self, classifier: ComplexityClassifier | None = None) -> None:
        self.classifier = classifier or ComplexityClassifier()

    def analyze(self, text: str) -> list[TaskStep]:
        kind = self.classifier.classify(text)
        if kind == TaskComplexity.SIMPLE:
            return [
                TaskStep(
                    id="step_0",
                    title="直接执行",
                    description=text,
                    dispatch="sync",
                )
            ]

        segments = [part.strip() for part in _SPLIT_RE.split(text) if part.strip()]
        if kind == TaskComplexity.COMPLEX and len(segments) < 2:
            segments = ["分析需求并拆解任务", text]
        if len(segments) > 6:
            segments = segments[:6]

        steps: list[TaskStep] = []
        for index, segment in enumerate(segments):
            dispatch = "async" if _ASYNC_RE.search(segment) else "sync"
            steps.append(
                TaskStep(
                    id=f"step_{index}",
                    title=segment[:20] or f"步骤 {index + 1}",
                    description=segment,
                    dispatch=dispatch,
                )
            )
        return steps
