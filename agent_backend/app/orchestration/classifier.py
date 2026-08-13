"""Rule-based task complexity classification."""

from __future__ import annotations

from agent_backend.app.orchestration.models import TaskComplexity

_COMPLEX_MARKERS = (
    "多模块",
    "复杂",
    "全流程",
    "从0到1",
    "系统",
    "重构整个",
    "拆解",
    "多阶段",
    "multi-agent",
    "multiagent",
)
_ASYNC_MARKERS = ("异步", "并行", "同时", "后台", "async", "parallel")


class ComplexityClassifier:
    @staticmethod
    def classify(text: str) -> TaskComplexity:
        lowered = text.lower()
        if any(marker in lowered for marker in _COMPLEX_MARKERS):
            return TaskComplexity.COMPLEX
        if any(marker in lowered for marker in _ASYNC_MARKERS):
            return TaskComplexity.ASYNC
        return TaskComplexity.SIMPLE
