"""Runtime dependency container."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from threading import Lock
from typing import Any

from agent_backend.app.config import Settings
from agent_backend.app.instructions.loader import InstructionLoader
from agent_backend.app.memory.compressor import MemoryCompressor
from agent_backend.app.memory.consolidator import MemoryConsolidator
from agent_backend.app.memory.retriever import MemoryRetriever
from agent_backend.app.memory.store import MemoryStore
from agent_backend.app.memory.summarizer import MemorySummarizer
from agent_backend.app.observability.events import EventBus
from agent_backend.app.observability.usage import UsageRecorder
from agent_backend.app.projects.manager import ProjectManager
from agent_backend.app.sessions.manager import SessionManager
from agent_backend.app.skills.registry import SkillRegistry
from agent_backend.app.storage.database import Database
from agent_backend.app.tools.builtin import build_builtin_tools
from agent_backend.app.tools.executor import ToolExecutor
from agent_backend.app.tools.registry import ToolContext, ToolRegistry, ToolRunner


class AgentAborted(RuntimeError):
    """Raised inside graph nodes when the current turn is aborted."""


class AbortController:
    def __init__(self) -> None:
        self._flags: dict[str, bool] = {}
        self._lock = Lock()

    def abort(self, session_id: str) -> None:
        with self._lock:
            self._flags[session_id] = True

    def check(self, session_id: str | None) -> None:
        if session_id is None:
            return
        with self._lock:
            if self._flags.get(session_id):
                raise AgentAborted(f"turn aborted for session {session_id}")

    def clear(self, session_id: str) -> None:
        with self._lock:
            self._flags.pop(session_id, None)


@dataclass
class RuntimeContext:
    settings: Settings
    db: Database
    session_manager: SessionManager
    project_manager: ProjectManager
    memory_store: MemoryStore
    memory_retriever: MemoryRetriever
    instruction_loader: InstructionLoader
    skill_registry: SkillRegistry
    tool_registry: ToolRegistry
    tool_runner: ToolRunner
    tool_executor: ToolExecutor
    event_bus: EventBus
    usage_recorder: UsageRecorder
    compressor: MemoryCompressor
    summarizer: MemorySummarizer
    consolidator: MemoryConsolidator
    abort_controller: AbortController
    user_home: Path
    _graph: Any | None = None
    _graph_lock: Lock = field(default_factory=Lock)

    @classmethod
    def from_settings(cls, settings: Settings, db: Database) -> RuntimeContext:
        skill_registry = SkillRegistry(db, settings.skill_dirs)
        memory_store = MemoryStore(db)
        tool_context = ToolContext(
            project_root=settings.project_root,
            max_output_bytes=settings.max_tool_output_bytes,
            user_home=Path.home(),
            git_backed_writes=settings.git_backed_writes,
            terminal_timeout_seconds=settings.terminal_timeout_seconds,
        )
        tool_context.skill_registry = skill_registry
        tool_registry = ToolRegistry(build_builtin_tools())
        tool_runner = ToolRunner(tool_registry, tool_context)
        tool_executor = ToolExecutor(tool_runner, retries=settings.tool_retry_limit)
        return cls(
            settings=settings,
            db=db,
            session_manager=SessionManager(db),
            project_manager=ProjectManager(db),
            memory_store=memory_store,
            memory_retriever=MemoryRetriever(memory_store),
            instruction_loader=InstructionLoader(settings.instruction_filenames),
            skill_registry=skill_registry,
            tool_registry=tool_registry,
            tool_runner=tool_runner,
            tool_executor=tool_executor,
            event_bus=EventBus(db),
            usage_recorder=UsageRecorder(db),
            compressor=MemoryCompressor(db),
            summarizer=MemorySummarizer(db),
            consolidator=MemoryConsolidator(db),
            abort_controller=AbortController(),
            user_home=Path.home(),
        )

    def get_graph(self) -> Any:
        with self._graph_lock:
            if self._graph is None:
                from agent_backend.app.core.graph import build_agent_graph

                self._graph = build_agent_graph(self)
            return self._graph
