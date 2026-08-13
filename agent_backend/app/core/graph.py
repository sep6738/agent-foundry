"""LangGraph state machine for a multi-turn agent loop with HITL support."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from langchain_core.messages import HumanMessage
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from agent_backend.app.core.context import RuntimeContext
from agent_backend.app.core.context_builder import build_system_prompt
from agent_backend.app.core.model import build_chat_model
from agent_backend.app.core.state import AgentMessage, AgentState
from agent_backend.app.instructions.loader import InstructionFile
from agent_backend.app.memory.compressor import estimate_tokens
from agent_backend.app.memory.scoring import extract_keywords
from agent_backend.app.observability.events import Event
from agent_backend.app.sessions.checkpointer import DatabaseCheckpointer
from agent_backend.app.tools.audit import audit_tool_call
from agent_backend.app.tools.registry import ToolContext


def _project_root(state: AgentState, context: RuntimeContext) -> Path:
    return Path(state.get("project_root") or context.settings.project_root).resolve()


def _stream_llm(
    context: RuntimeContext,
    state: AgentState,
    model,
    prompt: str,
) -> str:
    session_id = _session_id(state)
    context.event_bus.publish(
        Event(
            type="llm_started",
            session_id=session_id,
            payload={"input_chars": len(prompt)},
        )
    )
    content_parts: list[str] = []
    thinking_parts: list[str] = []
    for chunk in model.stream([HumanMessage(content=prompt)]):
        reasoning = None
        if isinstance(getattr(chunk, "additional_kwargs", None), dict):
            reasoning = chunk.additional_kwargs.get("reasoning_content")
        if reasoning:
            text = str(reasoning)
            thinking_parts.append(text)
            context.event_bus.publish(
                Event(
                    type="thinking_delta",
                    session_id=session_id,
                    payload={"delta": text},
                )
            )
        content = getattr(chunk, "content", "")
        if content:
            content_parts.append(str(content))
    context.event_bus.publish(
        Event(
            type="llm_finished",
            session_id=session_id,
            payload={
                "output_chars": sum(len(part) for part in content_parts),
                "thinking_chars": sum(len(part) for part in thinking_parts),
            },
        )
    )
    return "".join(content_parts) or "".join(thinking_parts)


def start_turn(state: AgentState, context: RuntimeContext) -> dict[str, Any]:
    context.abort_controller.check(_session_id(state))
    return {
        "tool_results": [],
        "response": "",
        "needs_tool": False,
        "finished": False,
        "flags": {},
    }


def _session_id(state: AgentState) -> str | None:
    return state.get("session_id")


def load_instructions(state: AgentState, context: RuntimeContext) -> dict[str, Any]:
    context.abort_controller.check(_session_id(state))
    bundle = context.instruction_loader.load(
        _project_root(state, context),
        user_home=context.user_home,
        trusted_roots=tuple(Path(root) for root in context.settings.trusted_project_roots),
    )
    files = list(bundle.files)
    session_id = _session_id(state)
    if session_id:
        for item in context.session_manager.get_session_instructions(session_id):
            key = str(item["key"])
            content = str(item["content"])
            files.append(
                InstructionFile(
                    name=f"session:{key}",
                    path=f"session:{key}",
                    priority=1000,
                    sections={"session": content},
                    content=content,
                )
            )
    bundle.files = files
    context.event_bus.publish(
        Event(
            type="instruction_loaded",
            session_id=session_id,
            payload={"files": [file.path for file in files]},
        )
    )
    return {"instructions": bundle}


def retrieve_memory(state: AgentState, context: RuntimeContext) -> dict[str, Any]:
    context.abort_controller.check(_session_id(state))
    query = state.get("current_query", "")
    budget = max(200, int(context.settings.default_token_budget * 0.1))
    facts = context.memory_retriever.retrieve(
        user_id=state["user_id"],
        query=query,
        budget_tokens=budget,
        limit=5,
    )
    return {"memory_facts": facts}


def load_skills(state: AgentState, context: RuntimeContext) -> dict[str, Any]:
    context.abort_controller.check(_session_id(state))
    skills = context.skill_registry.list_skills(
        _project_root(state, context),
        user_home=context.user_home,
    )
    return {"skills": skills}


def build_context(state: AgentState, context: RuntimeContext) -> dict[str, Any]:
    context.abort_controller.check(_session_id(state))
    raw = list(state.get("messages", []))
    working = list(state.get("context_messages") or [])
    seen = {message.message_id for message in working}
    for message in raw:
        if message.message_id and message.message_id not in seen:
            working.append(message)
            seen.add(message.message_id)
    if not working:
        working = list(raw)
    return {"context_messages": working}


def plan(state: AgentState, context: RuntimeContext) -> dict[str, Any]:
    context.abort_controller.check(_session_id(state))
    tool_rounds = int(state.get("tool_rounds", 0))
    if tool_rounds >= context.settings.max_tool_rounds:
        return {
            "response": "已达到最大工具调用轮数，停止继续调用工具。",
            "finished": True,
            "needs_tool": False,
        }

    model = build_chat_model(context.settings)
    prompt = _build_prompt(state, context)
    text = _stream_llm(context, state, model, prompt)
    tool_request = _parse_tool_request(text)

    if not tool_request:
        return {
            "tool_request": None,
            "needs_tool": False,
            "response": text,
            "finished": True,
        }

    tool_name = str(tool_request.get("tool", ""))
    args = tool_request.get("args") or {}
    tool = context.tool_registry.get(tool_name)
    if tool is None:
        return {
            "tool_request": None,
            "needs_tool": False,
            "response": f"工具不存在：{tool_name}",
            "finished": True,
        }
    flags = dict(state.get("flags") or {})
    approved_tools = list(flags.get("approved_tools", []))
    if _tool_key(tool_name, args) in flags.get("tool_done", {}):
        return {
            "tool_request": None,
            "needs_tool": False,
            "response": f"工具 {tool_name} 已完成，继续下一步。",
            "finished": True,
        }
    audit = audit_tool_call(tool, args, context.settings.audit_level)
    if audit.dangerous:
        context.event_bus.publish(
            Event(
                type="dangerous_command_detected",
                session_id=_session_id(state),
                payload={"purpose": audit.purpose, "risk": audit.risk},
            )
        )
    if audit.requires_approval and tool_name not in approved_tools:
        decision = interrupt(
            {
                "type": "tool_approval",
                "tool": tool_name,
                "args": args,
                "session_id": _session_id(state),
                "purpose": audit.purpose,
                "risk": audit.risk,
                "dangerous": audit.dangerous,
                "reason": audit.reason or f"工具 {tool_name} 需要人工审批",
            }
        )
        approved = bool(decision.get("approved")) if isinstance(decision, dict) else bool(decision)
        if not approved:
            return {
                "tool_request": None,
                "needs_tool": False,
                "response": "操作已取消：未获得人工审批。",
                "finished": True,
            }
        flags["approved_tools"] = approved_tools + [tool_name]

    context.event_bus.publish(
        Event(
            type="tool_call_started",
            session_id=_session_id(state),
            payload={"tool": tool_name, "args": args},
        )
    )
    return {
        "tool_request": tool_request,
        "needs_tool": True,
        "finished": False,
        "tool_rounds": tool_rounds + 1,
        "flags": flags,
    }


def _parse_tool_request(text: str) -> dict[str, Any] | None:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        lines = cleaned.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        cleaned = "\n".join(lines).strip()
    try:
        parsed = json.loads(cleaned)
        if isinstance(parsed, dict) and parsed.get("tool"):
            return parsed
    except json.JSONDecodeError:
        pass
    decoder = json.JSONDecoder()
    cursor = 0
    while True:
        start = cleaned.find("{", cursor)
        if start < 0:
            return None
        try:
            parsed, end = decoder.raw_decode(cleaned, start)
            if isinstance(parsed, dict) and parsed.get("tool"):
                return parsed
            cursor = end
        except json.JSONDecodeError:
            cursor = start + 1


def _tool_key(tool_name: str, args: dict[str, Any]) -> str:
    return json.dumps(
        {"tool": tool_name, "args": args},
        sort_keys=True,
        ensure_ascii=False,
    )


def decide(state: AgentState) -> str:
    return "execute_tools" if state.get("needs_tool") else "respond"


def execute_tools(state: AgentState, context: RuntimeContext) -> dict[str, Any]:
    context.abort_controller.check(_session_id(state))
    request = state.get("tool_request") or {}
    tool_name = str(request.get("tool", ""))
    args = request.get("args") or {}

    def sink(event_type: str, payload: dict[str, Any]) -> None:
        context.event_bus.publish(
            Event(type=event_type, session_id=_session_id(state), payload=payload)
        )

    tool_context = ToolContext(
        project_root=_project_root(state, context),
        max_output_bytes=context.settings.max_tool_output_bytes,
        skill_registry=context.skill_registry,
        user_home=context.user_home,
        git_backed_writes=context.settings.git_backed_writes,
        terminal_timeout_seconds=context.settings.terminal_timeout_seconds,
        event_sink=sink,
    )
    result = asyncio.run(context.tool_executor.run(tool_name, args, context=tool_context))
    flags = dict(state.get("flags") or {})
    if result.get("ok"):
        flags.setdefault("tool_done", {})[_tool_key(tool_name, args)] = True
    context.session_manager.record_tool_call(
        _session_id(state) or "",
        tool_name,
        args,
        result,
        status=1 if result.get("ok") else 0,
    )
    entry_id = context.session_manager.append_entry(
        _session_id(state) or "",
        "tool_result",
        {
            "tool": tool_name,
            "ok": bool(result.get("ok")),
            "content": str(result.get("output") or result.get("error") or ""),
            "truncated": bool(result.get("truncated")),
        },
    )
    context.event_bus.publish(
        Event(
            type="tool_call_completed",
            session_id=_session_id(state),
            payload={"tool": tool_name, "ok": bool(result.get("ok"))},
        )
    )
    if tool_name == "read_skill" and result.get("ok"):
        skill_name = str(args.get("name", ""))
        context.skill_registry.record_invocation(
            session_id=_session_id(state) or "",
            skill_name=skill_name,
            mode="auto",
            result="ok",
            duration_ms=int(result.get("duration_ms", 0)),
        )
        context.event_bus.publish(
            Event(
                type="skill_invoked",
                session_id=_session_id(state),
                payload={"skill": skill_name, "mode": "auto"},
            )
        )
    messages = list(state.get("messages", []))
    messages.append(
        AgentMessage(
            role="tool",
            content=str(result.get("output") or result.get("error") or ""),
            tool_name=tool_name,
            message_id=entry_id,
        )
    )
    return {
        "messages": messages,
        "tool_results": [result],
        "tool_request": None,
        "needs_tool": False,
        "flags": flags,
    }


def respond(state: AgentState, context: RuntimeContext) -> dict[str, Any]:
    response = state.get("response", "")
    if not response:
        tool_results = state.get("tool_results", [])
        last_tool = tool_results[-1] if tool_results else {}
        if last_tool.get("ok"):
            response = f"工具执行完成：\n{str(last_tool.get('output', ''))[:1000]}"
        else:
            response = f"工具执行失败：{last_tool.get('error', 'unknown error')}"
    _emit_deltas(context, _session_id(state), response)
    return {"response": response, "finished": True}


def save_memory(state: AgentState, context: RuntimeContext) -> dict[str, Any]:
    query = (state.get("current_query") or "").strip()
    if len(query) >= 8:
        if "偏好" in query or "喜欢" in query:
            kind = "preference"
        elif any(marker in query for marker in ("决定", "采用", "选择", "确认")):
            kind = "decision"
        else:
            kind = "fact"
        fact = context.memory_store.save_fact(
            user_id=state["user_id"],
            session_id=_session_id(state),
            subject=query[:64],
            content=query,
            kind=kind,
            tags=[kind],
            keywords=extract_keywords(query),
            scope="user",
            importance=0.4,
            confidence=0.5,
        )
        context.event_bus.publish(
            Event(
                type="memory_written",
                session_id=_session_id(state),
                payload={"memory_id": fact.id, "kind": fact.kind},
            )
        )
    return {}


def update_summary(state: AgentState, context: RuntimeContext) -> dict[str, Any]:
    context.summarizer.update(
        _session_id(state) or "",
        user_text=state.get("current_query", ""),
        response_text=state.get("response", ""),
    )
    return {}


def compress_context(state: AgentState, context: RuntimeContext) -> dict[str, Any]:
    context_messages = state.get("context_messages") or state.get("messages", [])
    current_tokens = sum(estimate_tokens(message.content) for message in context_messages)
    budget = context.settings.default_token_budget
    if not context.compressor.should_compress(
        budget,
        current_tokens,
        context.settings.compression_trigger_ratio,
    ):
        return {}
    session_id = _session_id(state)
    context.event_bus.publish(
        Event(
            type="compression_started",
            session_id=session_id,
            payload={"trigger": "budget_warning", "levels": [1, 2, 3]},
        )
    )
    summary = context.memory_store.summarize(session_id or "")
    model = None
    if context.settings.model_provider != "stub" and context.settings.model_api_key:
        model = build_chat_model(context.settings)
    outcome = context.compressor.compress(
        session_id or "",
        budget,
        [message.to_dict() for message in state.get("messages", [])],
        summary,
        model=model,
    )
    new_messages = [
        AgentMessage(
            role=str(item.get("role", "summary")),
            content=str(item.get("content", "")),
            message_id=str(item.get("id", "")),
            tool_name=item.get("tool_name"),
        )
        for item in outcome.context_messages
    ]
    context.event_bus.publish(
        Event(
            type="compression_completed",
            session_id=session_id,
            payload={
                "levels_used": outcome.result.levels_used,
                "freed_tokens": outcome.result.tokens_before - outcome.result.tokens_after,
            },
        )
    )
    return {
        "context_messages": new_messages,
        "flags": {"compressed": True},
    }


def _emit_deltas(context: RuntimeContext, session_id: str | None, text: str) -> None:
    step = 40
    for start in range(0, len(text), step):
        context.event_bus.publish(
            Event(
                type="message_delta",
                session_id=session_id,
                payload={"delta": text[start : start + step]},
            )
        )


def _build_prompt(state: AgentState, context: RuntimeContext) -> str:
    return build_system_prompt(state, context)


def build_agent_graph(context: RuntimeContext):
    graph = StateGraph(AgentState)
    graph.add_node("start_turn", lambda state: start_turn(state, context))
    graph.add_node("load_instructions", lambda state: load_instructions(state, context))
    graph.add_node("retrieve_memory", lambda state: retrieve_memory(state, context))
    graph.add_node("load_skills", lambda state: load_skills(state, context))
    graph.add_node("build_context", lambda state: build_context(state, context))
    graph.add_node("plan", lambda state: plan(state, context))
    graph.add_node("execute_tools", lambda state: execute_tools(state, context))
    graph.add_node("respond", lambda state: respond(state, context))
    graph.add_node("save_memory", lambda state: save_memory(state, context))
    graph.add_node("update_summary", lambda state: update_summary(state, context))
    graph.add_node("compress_context", lambda state: compress_context(state, context))
    graph.add_edge(START, "start_turn")
    graph.add_edge("start_turn", "load_instructions")
    graph.add_edge("load_instructions", "retrieve_memory")
    graph.add_edge("retrieve_memory", "load_skills")
    graph.add_edge("load_skills", "build_context")
    graph.add_edge("build_context", "plan")
    graph.add_conditional_edges(
        "plan",
        decide,
        {"execute_tools": "execute_tools", "respond": "respond"},
    )
    graph.add_edge("execute_tools", "build_context")
    graph.add_edge("respond", "save_memory")
    graph.add_edge("save_memory", "update_summary")
    graph.add_edge("update_summary", "compress_context")
    graph.add_edge("compress_context", END)
    serializer = JsonPlusSerializer(
        allowed_msgpack_modules=[
            ("agent_backend.app.core.state", "AgentMessage"),
            ("agent_backend.app.instructions.loader", "InstructionFile"),
            ("agent_backend.app.instructions.loader", "InstructionBundle"),
            ("agent_backend.app.memory.store", "MemoryFact"),
            ("agent_backend.app.skills.registry", "SkillMeta"),
        ]
    )
    return graph.compile(checkpointer=DatabaseCheckpointer(context.db, serde=serializer))
