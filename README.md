# Agent Foundry

> A self-contained, open-source AI agent backend: multi-session, memory-backed, tool-calling, with human-in-the-loop approval and multi-agent orchestration, built on Flask, LangChain, and LangGraph.

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
![Python](https://img.shields.io/badge/Python-3.11%2B-3776AB.svg)
![Stack](https://img.shields.io/badge/Flask%20%2B%20LangChain%20%2B%20LangGraph-000000.svg)

Agent Foundry is a complete agent **backend service**, not a demo notebook. It exposes a real REST + SSE API and runs a full agent lifecycle in production shape: project instruction injection, long-term memory, a skill system, safe tool execution, human approval gates, context compression, and subagent orchestration. It runs **out of the box with zero API keys** (deterministic stub model) and switches to any OpenAI-compatible model via environment variables.

## Table of Contents

- [How it works](#how-it-works)
- [Key features](#key-features)
- [Architecture](#architecture)
- [Quick start](#quick-start)
- [Configuration](#configuration)
- [API reference](#api-reference)
- [Development](#development)
- [Contributing](#contributing)
- [Security](#security)
- [License](#license)

## How it works

Every user message becomes a turn through a single LangGraph state machine:

```text
start_turn
  -> load_instructions   # AGENTS.md / CLAUDE.md / session-scoped instructions
  -> retrieve_memory     # FTS5 keyword retrieval, budget- and score-bounded
  -> load_skills         # builtin / user / project SKILL.md index
  -> build_context       # assemble the working message window
  -> plan                # LLM decides: answer directly or emit a tool request
     |
     +--- tool JSON? ---> execute_tools -> build_context (loop, max 8 rounds)
     |
     +--- answer ------> respond -> save_memory -> update_summary
                          -> compress_context -> END
```

- The **plan** node asks the model to either answer directly or emit strict JSON such as `{"tool":"read_file","args":{"path":"README.md"}}`; fenced or inline JSON is parsed.
- Tool results join the conversation and the loop continues up to `MAX_TOOL_ROUNDS`.
- **Human-in-the-loop** uses LangGraph interrupts: dangerous or approval-required calls pause the turn, the session enters `awaiting_human`, and `POST /v1/sessions/{id}/human/approve` resumes it from the persisted checkpoint.
- Every checkpoint is persisted to SQLite by a custom `BaseCheckpointSaver` (graph_checkpoints tables), so interrupted turns survive restarts.

## Key features

### Long-term memory without embeddings

- **SQLite FTS5 full-text search** with bm25 ranking plus a LIKE fallback, fed by database triggers; no vector store, no embedding API, no extra infrastructure.
- **Structured scoring** (memory/scoring.py) blends keyword hits, subject/tag match, recency decay, importance, confidence, scope, and rank into one deterministic score.
- **Versioned facts**: conflicting updates supersede old versions; high-confidence conflicts are flagged `needs_review` and can be confirmed or discarded through the API.
- **TTL support and cross-session consolidation** promote running session summaries into durable user-level knowledge facts.

### Progressive four-level context compression

Claude Code-style budget management kicks in when a session exceeds `COMPRESSION_TRIGGER_RATIO` of the token budget:

| Level | Strategy |
| --- | --- |
| L1 | Drop low-value turns and empty tool results |
| L2 | Truncate old long tool outputs to a pointer + head excerpt |
| L3 | Replace pre-window history with the maintained running summary |
| L4 | Model-generated structured summary (only when a real LLM is configured) |

Every run is recorded in compression_records with tokens freed and entries removed, and can be triggered manually via `POST /v1/memories/compress`.

### Running summaries at zero API cost

memory/summarizer.py keeps a structured summary (goals, progress, decisions, open questions, key facts) with rule-based extraction - deterministic, free, and consumed by L3 compression.

### Skill system

- Skills are `SKILL.md` files with YAML frontmatter from three scopes: **builtin** (e.g. `code-review`), **user** (`~/.agent/skills`), **project** (`.agent/skills`, `.claude/skills`).
- Frontmatter validation (name format, required fields, 64KB limit), versioned edits, invocation tracking, and an FTS index.
- `run_skill_script` executes `.py` scripts bundled under scripts/, confined to the skill directory with a timeout.

### Subagent and multi-agent orchestration

Non-simple requests skip the plain loop. `TaskOrchestrator` classifies the request (simple / async / complex) and, for async or complex tasks, runs a pipeline:

```text
classifier -> planner (decompose into steps) -> scheduler (sync/async marking)
           -> HR recruiter (assign skills to employee agents)
           -> SubAgentExecutor (each employee runs in its own session;
              async steps run in parallel via ThreadPoolExecutor)
           -> AuditMonitor (background thread relays live sub-agent events
              and publishes per-agent audit summaries)
```

Planner, Scheduler, and Recruiter are **LLM-driven when a model is configured** and fall back to deterministic rules otherwise - same request shape, zero setup.

### Safety-first tool execution

- Seven built-in tools: `list_directory`, `read_file`, `write_file`, `run_command`, `read_skill`, `edit_skill`, `run_skill_script`.
- **Directory confinement**: paths resolve strictly inside the project root; `run_command` rejects commands that escape it (cd .., absolute paths, other drives).
- **Audit policy** in three levels (`AUDIT_LEVEL=1|2|3`): dangerous patterns (DROP DATABASE, rm -rf /, mkfs, shutdown, ...) are detected and block or require approval; dependency-modifying commands (pip/npm/uv install ...) require approval at balanced level.
- **Git-backed writes**: `write_file` can auto-commit every change into the project repository.
- Optional API-key auth with per-key tenant mapping; optional human approval on every write.

### Real-time SSE observability

`POST /v1/sessions/{id}/messages` returns an SSE stream with model thinking deltas, answer deltas, tool-call lifecycle, and live command stdout/stderr. Events are persisted and replayable via `GET /v1/sessions/{id}/events`; `X-Request-Id` trace ids propagate end-to-end.

## Architecture

```text
HTTP/SSE clients
      |
      v
api/ (blueprints, middleware, validation)     app/
      |                                        |
      v                                        v
services/ (session & conversation services) -> core/  LangGraph graph + runtime
                                                 |     |     |     |
                                                 v     v     v     v
                                         memory/ tools/ skills/ instructions/
                                                 |
                                                 v
                                         orchestration/ (subagents, roles, audit)
                                                 |
                                                 v
                                         storage/ (SQLAlchemy + SQLite FTS5)
```

Dependencies point in one direction: API -> services -> runtime/memory -> storage. Graph nodes are pure functions receiving a `RuntimeContext` (dependency injection); no node touches Flask request/response objects.

```text
agent_backend/app/
  api/             REST and SSE blueprints, JSON errors, request validation
  auth/            optional API-key authentication with per-key user mapping
  services/        session and conversation application services
  core/            LangGraph graph, runtime, HITL resume, system prompt builder
  orchestration/   complexity classifier, planner, scheduler, recruiter, executor, audit monitor
  instructions/    AGENTS.md / CLAUDE.md discovery, caching, bounded prompt injection
  skills/          registry, validation, editor, executable script runner
  memory/          store, retriever, scoring, summarizer, compressor, consolidator
  tools/           registry, executor (retries), builtins, audit policy
  sessions/        session manager, repository, SQLite LangGraph checkpointer
  projects/        project folder registration and resolution
  storage/         SQLAlchemy models, FTS5 bootstrap, database handles
  observability/   event bus, SSE, trace propagation, usage recording
alembic/           database migrations
evals/             scenario-based evaluations (JSON scenarios)
tests/             14 pytest modules, run without network or API keys
wsgi.py            Flask entry point
```

## Quick start

Requirements: Python 3.11+ and [uv](https://docs.astral.sh/uv/).

```powershell
uv sync
uv run flask --app wsgi run --debug
```

Verify the service:

```powershell
curl http://127.0.0.1:5000/health
# {"status":"ok"}
```

Try a full agent turn:

```powershell
$sid = (curl.exe -s -X POST http://127.0.0.1:5000/v1/sessions -H "Content-Type: application/json" -d '{"user_id":"demo","title":"demo"}' | ConvertFrom-Json).id
curl.exe -s -N -X POST "http://127.0.0.1:5000/v1/sessions/$sid/messages" -H "Content-Type: application/json" -d '{"message":"List the files in the project root."}'
```

The stub model answers deterministically and even demonstrates tool calling (`list_directory`) and skills (`code-review`) with no API key. To use a real OpenAI-compatible model:

```powershell
$env:MODEL_API_KEY = "sk-..."
$env:MODEL_NAME = "gpt-5.4"
$env:MODEL_BASE_URL = "https://api.openai.com/v1"   # optional
uv run flask --app wsgi run
```

## Configuration

All settings come from environment variables (agent_backend/app/config.py):

| Variable | Default | Meaning |
| --- | --- | --- |
| `APP_ENV` | development | Runtime environment |
| `DATABASE_URL` | sqlite:///./data/agent.db | SQLAlchemy database URL |
| `MODEL_PROVIDER` | stub | `stub` or any real provider (e.g. `openai`) |
| `MODEL_NAME` | gpt-4o-mini | Model name for the real LLM |
| `MODEL_API_KEY` | - | Falls back to `OPENAI_API_KEY` |
| `MODEL_BASE_URL` | - | Custom (OpenAI-compatible) base URL |
| `DEFAULT_TOKEN_BUDGET` / `COMPRESSION_TRIGGER_RATIO` | 16000 / 0.9 | Context budget and compression threshold |
| `INSTRUCTION_BUDGET_RATIO` / `INSTRUCTION_FILENAMES` | 0.15 / AGENTS.md,CLAUDE.md | Prompt budget for injected instructions |
| `SKILL_DIRS` | .agent/skills,.claude/skills | Project skill directories |
| `MAX_TOOL_OUTPUT_BYTES` / `MAX_TOOL_ROUNDS` / `TOOL_RETRY_LIMIT` | 64000 / 8 / 2 | Tool execution limits |
| `HUMAN_APPROVAL_REQUIRED` | 1 | Force approval on write-type tool calls |
| `AUDIT_LEVEL` | 2 | 1=strict, 2=balanced, 3=trust |
| `GIT_BACKED_WRITES` | 1 | Auto-commit `write_file` changes |
| `TERMINAL_TIMEOUT_SECONDS` | 30 | Default command timeout |
| `API_KEYS` / `API_KEY_USERS` | - | Comma-separated keys; `key:user` mapping for tenants |
| `TRUSTED_PROJECT_ROOTS` / `PROJECT_ROOT` | - / cwd | Roots allowed for instruction walking and project folders |

## API reference

### Sessions and messages

| Method | Path | Description |
| --- | --- | --- |
| POST | `/v1/sessions` | Create a session (optionally bound to a project) |
| GET | `/v1/sessions` | List sessions (`?user_id=`) |
| GET | `/v1/sessions/{id}` | Get a session |
| DELETE | `/v1/sessions/{id}` | Delete a session |
| POST | `/v1/sessions/{id}/messages` | Run a turn; **SSE stream** with live deltas and tool/command events |
| GET | `/v1/sessions/{id}/history` | Full entry log (messages, tool results, human requests, usage) |
| GET | `/v1/sessions/{id}/events` | Persisted observability events |
| POST | `/v1/sessions/{id}/abort` | Abort the running turn |
| POST | `/v1/sessions/{id}/compact` | Manually trigger context compression |
| POST | `/v1/sessions/{id}/human/approve` | Approve/reject a paused tool call (HITL resume) |
| GET/POST | `/v1/sessions/{id}/instructions` | List / inject session-scoped instructions |
| DELETE | `/v1/sessions/{id}/instructions/{key}` | Remove a session instruction |

### Memories

| Method | Path | Description |
| --- | --- | --- |
| GET/POST | `/v1/memories` | Search (`?q=`) / create facts (kind, tags, scope, importance, confidence, ttl) |
| GET/PUT/DELETE | `/v1/memories/{id}` | Read / update (versioned) / forget |
| POST | `/v1/memories/{id}/confirm` | Confirm a `needs_review` fact (supersedes the older one) |
| POST | `/v1/memories/compress` | Manual compression for a session |
| POST | `/v1/memories/consolidate` | Promote running summaries to durable knowledge |

### Skills, tools, projects, instructions

| Method | Path | Description |
| --- | --- | --- |
| GET/POST | `/v1/skills` | List / create skills (validated frontmatter) |
| GET/PUT/DELETE | `/v1/skills/{name}` | Read / update (versioned) / delete a skill |
| POST | `/v1/skills/{name}/validate` | Validate skill content without saving |
| POST | `/v1/skills/{name}/use` | Inject a skill into a session as instructions |
| GET | `/v1/tools` | Tools with JSON schemas and permissions |
| GET/POST | `/v1/projects` (+ `/{id}`) | Register, list, view, delete project folders |
| DELETE | `/v1/projects/{id}` | Delete a project registration |
| GET | `/v1/instructions` | Discovered instruction files and rendered bundle |
| POST | `/v1/instructions/reload` | Drop the instruction cache and reload |
| GET | `/health` | Health check |
| GET | `/metrics` | DB row counts (sessions, tool calls, events, memory facts) |

Tenant identity is carried by `X-User-Id` (or the `user_id` field) when API keys are not configured; with `API_KEYS` set, `X-API-Key` / `Authorization: Bearer` authenticate and map to tenants.

## Development

```powershell
uv sync
uv run pytest                 # 14 modules; no network, no API keys (stub model)
uv run ruff check .           # lint
uv run ruff format --check .  # formatting
uv run ruff format .          # apply formatting
uv run python evals/run_evals.py   # scenario evaluations (instruction_following,
                                     memory_recall, skill_usage, tool_usage)
```

Database schema changes go through Alembic: add a revision and apply it before committing.

## Contributing

Contributions of all kinds are welcome: features, bug fixes, tests, docs, security hardening, and evals.

1. Fork the repository and create a feature branch.
2. Mirror the `app/` package layout under `tests/test_<module>.py`; keep real model calls out of unit tests.
3. Add scenario evaluations under `evals/scenarios/` when prompts, compression, memory, or skills change.
4. Run `uv run ruff format .`, `uv run ruff check .`, and `uv run pytest` before requesting review.
5. Open one pull request per concern and describe the motivation; include SSE event traces for API/SSE changes.

### AI-assisted maintainer workflow

This project is maintained with modern AI agent tooling. Maintainers use coding agents (e.g., OpenAI Codex CLI) for:

- **PR review and triage** - first-pass review of incoming pull requests, catching style, test, and security issues before human review; the project ships its own `code-review` builtin skill for exactly this workflow.
- **Maintainer automation** - release checklist validation, changelog drafting, and routine issue grooming.
- **Core OSS workflows** - keeping the test suite green and the codebase consistently formatted across commits.

If you contribute with a coding agent, please ensure the final commit is human-reviewed like any other.

## Security

See the audit policy in `agent_backend/app/tools/audit.py` for details; in short:

- Tools and commands are confined to the registered project directory; escape attempts are rejected before execution.
- Danger patterns and dependency-modifying commands are detected and gated behind human approval according to `AUDIT_LEVEL`.
- Agent writes can be Git-backed and human-approved (`GIT_BACKED_WRITES`, `HUMAN_APPROVAL_REQUIRED`).
- Optional API-key auth isolates tenants; filesystem/home/system roots are rejected as project folders.

To report a vulnerability, please contact the maintainers directly instead of opening a public issue.

## License

[MIT](LICENSE) (c) 2026 sep6738. See the [LICENSE](LICENSE) file for details.

[中文说明](README.zh-CN.md)
