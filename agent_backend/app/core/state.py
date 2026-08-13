"""Agent state types shared by graph nodes."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated, Any, TypedDict

from agent_backend.app.instructions.loader import InstructionBundle
from agent_backend.app.memory.store import MemoryFact
from agent_backend.app.skills.registry import SkillMeta


@dataclass
class AgentMessage:
    role: str
    content: str
    message_id: str = ""
    tool_name: str | None = None
    drop_low_value: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "role": self.role,
            "content": self.content,
            "id": self.message_id,
            "tool_name": self.tool_name,
            "drop_low_value": self.drop_low_value,
        }


def _concat(left: list[AgentMessage], right: list[AgentMessage]) -> list[AgentMessage]:
    return left + right


class AgentState(TypedDict, total=False):
    session_id: str
    user_id: str
    project_root: str
    current_query: str
    messages: Annotated[list[AgentMessage], _concat]
    context_messages: list[AgentMessage]
    instructions: InstructionBundle
    memory_facts: list[MemoryFact]
    skills: list[SkillMeta]
    tool_request: dict[str, Any] | None
    tool_results: list[dict[str, Any]]
    response: str
    needs_tool: bool
    finished: bool
    tool_rounds: int
    pending_human: dict[str, Any] | None
    flags: dict[str, bool]
