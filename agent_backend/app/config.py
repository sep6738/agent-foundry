"""Application configuration loaded from environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    app_env: str = field(default_factory=lambda: os.getenv("APP_ENV", "development"))
    database_url: str = field(
        default_factory=lambda: os.getenv("DATABASE_URL", "sqlite:///./data/agent.db")
    )
    model_provider: str = field(default_factory=lambda: os.getenv("MODEL_PROVIDER", "stub"))
    model_name: str = field(default_factory=lambda: os.getenv("MODEL_NAME", "gpt-4o-mini"))
    model_api_key: str | None = field(
        default_factory=lambda: os.getenv("MODEL_API_KEY") or os.getenv("OPENAI_API_KEY")
    )
    model_base_url: str | None = field(default_factory=lambda: os.getenv("MODEL_BASE_URL"))
    default_token_budget: int = field(
        default_factory=lambda: int(os.getenv("DEFAULT_TOKEN_BUDGET", "16000"))
    )
    compression_trigger_ratio: float = field(
        default_factory=lambda: float(os.getenv("COMPRESSION_TRIGGER_RATIO", "0.9"))
    )
    instruction_budget_ratio: float = field(
        default_factory=lambda: float(os.getenv("INSTRUCTION_BUDGET_RATIO", "0.15"))
    )
    instruction_filenames: tuple[str, ...] = field(
        default_factory=lambda: tuple(
            name.strip()
            for name in os.getenv("INSTRUCTION_FILENAMES", "AGENTS.md,CLAUDE.md").split(",")
            if name.strip()
        )
    )
    skill_dirs: tuple[str, ...] = field(
        default_factory=lambda: tuple(
            name.strip()
            for name in os.getenv("SKILL_DIRS", ".agent/skills,.claude/skills").split(",")
            if name.strip()
        )
    )
    max_tool_output_bytes: int = field(
        default_factory=lambda: int(os.getenv("MAX_TOOL_OUTPUT_BYTES", "64000"))
    )
    max_tool_rounds: int = field(default_factory=lambda: int(os.getenv("MAX_TOOL_ROUNDS", "8")))
    tool_retry_limit: int = field(default_factory=lambda: int(os.getenv("TOOL_RETRY_LIMIT", "2")))
    human_approval_required: bool = field(
        default_factory=lambda: (
            os.getenv("HUMAN_APPROVAL_REQUIRED", "1").lower() in {"1", "true", "yes", "on"}
        )
    )
    audit_level: int = field(default_factory=lambda: int(os.getenv("AUDIT_LEVEL", "2")))
    git_backed_writes: bool = field(
        default_factory=lambda: (
            os.getenv("GIT_BACKED_WRITES", "1").lower() in {"1", "true", "yes", "on"}
        )
    )
    terminal_timeout_seconds: int = field(
        default_factory=lambda: int(os.getenv("TERMINAL_TIMEOUT_SECONDS", "30"))
    )
    api_keys: tuple[str, ...] = field(
        default_factory=lambda: tuple(
            key.strip() for key in os.getenv("API_KEYS", "").split(",") if key.strip()
        )
    )
    api_key_users: dict[str, str] = field(
        default_factory=lambda: {
            part.split(":", 1)[0].strip(): part.split(":", 1)[1].strip()
            for part in os.getenv("API_KEY_USERS", "").split(",")
            if ":" in part and part.split(":", 1)[0].strip()
        }
    )
    trusted_project_roots: tuple[str, ...] = field(
        default_factory=lambda: tuple(
            root.strip()
            for root in os.getenv("TRUSTED_PROJECT_ROOTS", "").split(",")
            if root.strip()
        )
    )
    project_root: Path = field(
        default_factory=lambda: Path(os.getenv("PROJECT_ROOT", str(Path.cwd()))).resolve()
    )
