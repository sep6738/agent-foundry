"""Chat model abstraction: real OpenAI-compatible model or deterministic stub."""

from __future__ import annotations

import json
import re
from collections.abc import Iterator
from typing import Any, ClassVar

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, AIMessageChunk, BaseMessage, HumanMessage
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult
from langchain_openai import ChatOpenAI

from agent_backend.app.config import Settings


class StubChatModel(BaseChatModel):
    """Deterministic model so the project runs without an API key."""

    model_name: str = "stub"
    temperature: float = 0.0
    _tool_schema: ClassVar[dict[str, Any]] = {
        "list_directory": {
            "type": "object",
            "properties": {"path": {"type": "string", "default": "."}},
        },
        "read_file": {
            "type": "object",
            "required": ["path"],
            "properties": {"path": {"type": "string"}},
        },
    }

    @property
    def _llm_type(self) -> str:
        return "stub"

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: Any = None,
        **kwargs: Any,
    ) -> ChatResult:
        text = self._respond(messages)
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content=text))])

    def _stream(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: Any = None,
        **kwargs: Any,
    ) -> Iterator[ChatGenerationChunk]:
        text = self._respond(messages)
        if not text:
            yield ChatGenerationChunk(message=AIMessageChunk(content=""))
            return
        for chunk in text.split(" "):
            if not chunk:
                continue
            yield ChatGenerationChunk(message=AIMessageChunk(content=chunk + " "))

    def _respond(self, messages: list[BaseMessage]) -> str:
        last_user = ""
        has_tool_result = False
        history_text = ""
        for message in reversed(messages):
            if isinstance(message, HumanMessage):
                content = str(message.content)
                match = re.search(
                    r"<current_request>\s*(.*?)\s*</current_request>",
                    content,
                    re.DOTALL,
                )
                history = re.search(
                    r"<conversation_history>(.*?)</conversation_history>",
                    content,
                    re.DOTALL,
                )
                if history:
                    history_text = history.group(1)
                if match:
                    last_user = match.group(1)
                else:
                    last_user = content
                break
        lower = last_user.lower()
        content = ""
        if messages and isinstance(messages[-1], HumanMessage):
            content = str(messages[-1].content)
        memory = re.search(r"<memory_facts>(.*?)</memory_facts>", content, re.DOTALL)
        instructions = re.search(
            r"<project_instructions>(.*?)</project_instructions>",
            content,
            re.DOTALL,
        )
        if memory and ("language" in lower or "语言" in last_user):
            if "python" in memory.group(1).lower():
                return "Python"
        if memory and ("test command" in lower or "测试命令" in last_user):
            if "pytest" in memory.group(1).lower():
                return "Use pytest for tests."
        if instructions and ("test command" in lower or "测试命令" in last_user):
            if "pytest" in instructions.group(1).lower():
                return "Use pytest for tests and ruff for linting."
        if last_user and history_text:
            idx = history_text.rfind(last_user)
            if idx >= 0 and "[tool]" in history_text[idx:]:
                has_tool_result = True
        if has_tool_result and (
            "list" in lower
            or "read" in lower
            or "review" in lower
            or "目录" in last_user
            or "读取" in last_user
            or "代码审查" in last_user
            or "create skill" in lower
            or "编辑技能" in last_user
            or "创建技能" in last_user
        ):
            return ""
        if "review" in lower or "code review" in lower or "代码审查" in last_user:
            return json.dumps(
                {
                    "tool": "read_skill",
                    "args": {"name": "code-review"},
                },
                ensure_ascii=False,
            )
        if "create skill" in lower or "编辑技能" in last_user or "创建技能" in last_user:
            return json.dumps(
                {
                    "tool": "edit_skill",
                    "args": {
                        "name": "demo-skill",
                        "content": (
                            "---\nname: demo-skill\ndescription: demo skill\n"
                            "---\n\n## Steps\n1. Do the thing.\n"
                        ),
                    },
                },
                ensure_ascii=False,
            )
        if "list" in lower or "目录" in last_user:
            return json.dumps({"tool": "list_directory", "args": {"path": "."}}, ensure_ascii=False)
        if "read" in lower or "读取" in last_user:
            match = re.search(r"(?:read|读取)[^\w]*([\w./\\-]+\.\w+)", last_user)
            return json.dumps(
                {"tool": "read_file", "args": {"path": match.group(1) if match else "."}},
                ensure_ascii=False,
            )
        return (
            "Stub model response. Configure MODEL_API_KEY and MODEL_NAME to use a real model. "
            f"Received: {last_user[:200]}"
        )


def build_chat_model(settings: Settings) -> BaseChatModel:
    if settings.model_provider == "stub" or not settings.model_api_key:
        return StubChatModel()
    kwargs: dict[str, Any] = {
        "model": settings.model_name,
        "api_key": settings.model_api_key,
        "temperature": 0,
    }
    if settings.model_base_url:
        kwargs["base_url"] = settings.model_base_url
    return ChatOpenAI(**kwargs)
