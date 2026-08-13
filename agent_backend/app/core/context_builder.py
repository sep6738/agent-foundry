"""System prompt assembly and LLM message projection."""

from __future__ import annotations

from agent_backend.app.core.context import RuntimeContext
from agent_backend.app.core.state import AgentState
from agent_backend.app.instructions.injector import PromptInjector


def build_system_prompt(state: AgentState, context: RuntimeContext) -> str:
    settings = context.settings
    instruction_budget = max(
        500,
        int(settings.default_token_budget * settings.instruction_budget_ratio),
    )
    instructions = PromptInjector.inject(state.get("instructions"), instruction_budget)
    memory = "\n".join(
        f"- {fact.subject}: {fact.content}" for fact in state.get("memory_facts", [])
    )
    skills = "\n".join(
        f"- {skill.name}: {skill.description}" + (f"（{skill.when}）" if skill.when else "")
        for skill in state.get("skills", [])
    )
    tools = "\n".join(
        f"- {schema['function']['name']}: {schema['function']['description']}"
        for schema in context.tool_registry.schemas()
    )
    history = "\n".join(
        f"[{message.role}] {message.content}"
        for message in (state.get("context_messages") or state.get("messages", []))
    )
    query = state.get("current_query", "")
    return (
        "你是通用 Agent。请遵守项目指令，按需调用工具。"
        f"\n\n<project_instructions>\n{instructions or '（无）'}\n</project_instructions>"
        f"\n\n<memory_facts>\n{memory or '（无）'}\n</memory_facts>"
        f"\n\n<skill_index>\n{skills or '（无）'}\n</skill_index>"
        f"\n\n<tools>\n{tools or '（无）'}\n</tools>"
        f"\n\n<conversation_history>\n{history or '（无）'}\n</conversation_history>"
        f"\n\n<current_request>\n{query}\n</current_request>"
        '\n如果需要工具，只输出 JSON：{"tool": "工具名", "args": {...}}；否则直接回答。'
    )


def project_messages(state: AgentState) -> list[dict[str, str]]:
    """Project internal agent messages to the model-visible shape."""
    return [
        {"role": message.role, "content": message.content}
        for message in (state.get("context_messages") or state.get("messages", []))
    ]
