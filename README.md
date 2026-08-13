# Agent Foundry

一个面向求职与学习场景、可直接运行的多 Agent 后端项目。项目使用 Flask、LangChain 与 LangGraph 构建，重点演示如何从零实现一个具备长期记忆、项目指令注入、工具调用、人工审批、上下文压缩、Skill 体系、Subagent 与 Multi-Agent 编排的通用 Agent 后端服务。

## 项目亮点

- **单 Agent 核心循环**：指令加载、记忆检索、技能加载、规划、工具执行、回复、记忆写入、摘要更新、上下文压缩，全部通过 LangGraph 显式状态机完成。
- **长期记忆**：不使用 RAG 和 Embedding，采用 SQLite FTS5 关键词检索、结构化评分、事实版本化、运行中摘要和跨会话 consolidation。
- **分级上下文压缩**：借鉴 Claude Code 思路，实现丢弃低价值轮次、压缩长工具输出、运行中摘要替换、模型摘要兜底四级策略。
- **Subagent 与 Multi-Agent 编排**：任务先按复杂度分类，简单任务走单 Agent，复杂任务进入需求分析、排期分配、HR 招募、员工 Agent 执行与实时审计流水线。
- **模型驱动角色 + 规则兜底**：Planner、Scheduler、HR Recruiter 在配置真实模型时由 LLM 驱动，无模型时自动回退到确定性规则，保证项目始终可运行。
- **安全与审计**：三档审计等级、危险指令检测、命令越界拦截、项目目录隔离、Git 化文件写入。
- **实时 SSE 观测**：模型思考、最终输出、工具调用、终端 stdout/stderr 均可实时推送给前端。

## 技术栈

- Flask：REST API 与 SSE 流式输出
- LangChain：模型抽象与 Prompt
- LangGraph：状态机、Checkpointer、中断/恢复
- SQLite + SQLAlchemy：会话、记忆、事件、检查点存储
- SQLite FTS5：无向量关键词检索

## 快速开始

```powershell
uv sync
uv run flask --app wsgi run --debug
```

打开 <http://127.0.0.1:5000/health> 检查服务是否正常。

默认使用确定性 stub 模型，无需 API Key 即可运行。配置 `MODEL_API_KEY`、`MODEL_NAME` 与 `MODEL_BASE_URL` 后即可接入真实 OpenAI 兼容模型。

## 核心 API

```text
POST   /v1/sessions                    创建会话
GET    /v1/sessions                    列出会话
POST   /v1/sessions/{id}/messages      发送消息并接收 SSE 事件流
GET    /v1/sessions/{id}/history       查看会话历史
GET    /v1/sessions/{id}/events        回放会话事件
POST   /v1/sessions/{id}/abort         中止当前回合
POST   /v1/sessions/{id}/compact       手动触发上下文压缩
POST   /v1/sessions/{id}/human/approve 人工审批工具调用
GET    /v1/sessions/{id}/instructions  查看会话指令
POST   /v1/sessions/{id}/instructions  注入会话指令
DELETE /v1/sessions/{id}/instructions/{key}  移除会话指令

POST   /v1/projects                    注册项目文件夹
GET    /v1/projects                    列出项目
GET/DELETE /v1/projects/{id}           查看 / 删除项目

GET/POST /v1/memories                  检索 / 创建记忆
PUT/DELETE /v1/memories/{id}           更新 / 删除记忆
POST   /v1/memories/{id}/confirm       确认冲突事实
POST   /v1/memories/compress           手动压缩
POST   /v1/memories/consolidate        跨会话巩固

GET/POST /v1/skills                    列出 / 创建技能
GET/PUT/DELETE /v1/skills/{name}       读取 / 更新 / 删除技能
POST   /v1/skills/{name}/validate      校验技能
POST   /v1/skills/{name}/use           显式使用技能

GET    /v1/tools                       列出工具
GET    /health                         健康检查
GET    /metrics                        运行指标
```

## 运行配置

```text
APP_ENV, DATABASE_URL
MODEL_PROVIDER, MODEL_NAME, MODEL_API_KEY, MODEL_BASE_URL
DEFAULT_TOKEN_BUDGET, COMPRESSION_TRIGGER_RATIO
INSTRUCTION_BUDGET_RATIO, INSTRUCTION_FILENAMES
SKILL_DIRS, MAX_TOOL_OUTPUT_BYTES, MAX_TOOL_ROUNDS, TOOL_RETRY_LIMIT
AUDIT_LEVEL, GIT_BACKED_WRITES, TERMINAL_TIMEOUT_SECONDS
HUMAN_APPROVAL_REQUIRED, API_KEYS, API_KEY_USERS
TRUSTED_PROJECT_ROOTS, PROJECT_ROOT
```

## 项目结构

```text
agent_backend/
  app/
    api/            REST 与 SSE 蓝图、中间件、请求校验
    auth/           API Key 认证与租户身份
    services/       会话与对话应用服务
    core/           LangGraph 图、运行时、上下文构建
    orchestration/  Subagent 与 Multi-Agent 编排
    instructions/   项目指令发现与注入
    skills/         Skill 注册、编辑、运行
    memory/         记忆存储、检索、摘要、压缩、巩固
    tools/          工具注册、执行、审计
    sessions/       会话管理、数据库 Checkpointer
    projects/       项目文件夹管理
    storage/        SQLAlchemy 模型、FTS5、数据库初始化
    observability/  事件总线、trace、用量记录
alembic/            数据库迁移
evals/              场景化评测
tests/              单元与集成测试
wsgi.py             Flask 入口
```

## 开发命令

```powershell
uv sync
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv run python evals/run_evals.py
```
