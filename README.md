# sql_agent

可追踪的中英双语 PostgreSQL 业务数据 Agent。用户可以用中文或英文提问，后端 Agent 会通过只读 MCP 工具解析日期、检索业务规则、读取数据库结构、校验并执行受保护的 `SELECT` 查询，最后返回业务答案和结果表。

Traceable bilingual business data Agent for PostgreSQL. Users can ask questions in Chinese or English; the backend Agent uses read-only MCP tools to resolve dates, retrieve business rules, inspect schema, validate and execute guarded `SELECT` queries, then return a business answer and result table.

## 项目简介 / Overview

`sql_agent` 面向需要“用自然语言查业务数据库”的场景。它把大模型生成 SQL 的过程拆成可审计步骤，并在执行前后加入只读校验、业务规则检索、Schema 描述和结果追踪。

`sql_agent` is built for business data workflows where users query databases with natural language. It makes the LLM-to-SQL path auditable by adding read-only validation, business rule retrieval, schema inspection, and execution tracing around generated SQL.

## 架构 / Architecture

- 后端 API / Backend API: FastAPI service in `backend/app/main.py`.
- MCP 工具 / MCP tools: PostgreSQL and business rule tools in `backend/app/mcp/server.py`.
- PostgreSQL 访问 / PostgreSQL access: read-only SQL guard plus PostgreSQL read-only transaction execution.
- 业务规则 / Business rules: local folder search limited to `backend/business_rules`.
- 前端 / Frontend: Vite React business query console in `frontend`, with Chinese and English UI switching.

## 安全边界 / Security Boundaries

- PostgreSQL 只接受单条 `SELECT` 或只读 `WITH` 语句。
- PostgreSQL execution accepts only one `SELECT` or read-only `WITH` statement.
- 生成 SQL 会被服务端自动加上 `LIMIT`。
- Generated SQL is wrapped with a server-side `LIMIT`.
- PostgreSQL 会话使用 `SET TRANSACTION READ ONLY`。
- PostgreSQL sessions use `SET TRANSACTION READ ONLY`.
- Agent 通过 MCP 工具处理日期上下文、业务规则、Schema、SQL 校验和查询执行。
- The Agent calls MCP tools for date context, business rules, schema, SQL validation, and query execution.
- 业务规则搜索不调用 shell 命令，并拒绝绝对路径、目录逃逸、不支持的扩展名、符号链接和超大文件。
- Business rule search does not use shell commands, and rejects absolute paths, path escapes, unsupported extensions, symlinks, and oversized files.
- 本地密钥只放在 `.env`，该文件已被 Git 忽略。
- Local secrets live only in `.env`, which is ignored by Git.

## 本地安装 / Local Setup

先安装后端依赖，并从示例文件创建本地配置。

Install backend dependencies first, then create your local config from the example file.

```bash
uv sync --dev
cp .env.example .env
```

项目通过 `.python-version` 固定 Python 版本，并使用 `uv.lock` 保证依赖解析可复现。

The project pins Python through `.python-version` and uses `uv.lock` for repeatable dependency resolution.

安装前端依赖。

Install frontend dependencies.

```bash
cd frontend
npm install
```

## 运行 / Run

启动演示 PostgreSQL。

Start the demo PostgreSQL service.

```bash
make db-up
```

启动后端。

Start the backend.

```bash
make backend
# or: uv run uvicorn backend.app.main:app --reload --host 0.0.0.0 --port 8000
```

启动前端。

Start the frontend.

```bash
make frontend
```

启动 MCP server。

Start the MCP server.

```bash
make mcp
# or: uv run python -m backend.app.mcp.server
```

运行测试。

Run tests.

```bash
make test
# or: uv run python -m unittest discover backend/tests
```

重置演示数据。

Reset demo data.

```bash
make db-reset
```

## 演示数据 / Demo Data

演示 PostgreSQL 服务默认数据库是 `circle_demo`，业务 Schema 是 `aiinfra`。

The demo PostgreSQL service uses database `circle_demo`; the business schema is `aiinfra`.

演示表 / Demo tables:

- `aiinfra.clusters`
- `aiinfra.gpu_nodes`
- `aiinfra.teams`
- `aiinfra.workloads`
- `aiinfra.gpu_allocations`
- `aiinfra.daily_gpu_metrics`
- `aiinfra.capacity_events`

示例问题 / Example questions:

| 中文 | English |
| --- | --- |
| 今天的卡时使用率多少？ | What is today's GPU-hour utilization rate? |
| 这一周的卡时使用率多少？ | What is the GPU-hour utilization rate this week? |
| 现在 AI infra 总卡数是多少？ | How many total GPU cards does AI infra have now? |
| 最新一天各集群的卡时使用率是多少？ | What is each cluster's GPU-hour utilization rate on the latest day? |
| 哪些集群有容量压力？ | Which clusters have capacity pressure? |
| 最新一天单卡时成本是多少？ | What is the per-GPU-hour cost on the latest day? |
| 当前未解决的容量告警有哪些？ | What unresolved capacity alerts are currently open? |

## 配置 / Configuration

所有本地配置都放在 `.env`。先复制 `.env.example`，再替换所有 `change-me` 值。

All local configuration belongs in `.env`. Copy `.env.example` first, then replace every `change-me` value.

```bash
cp .env.example .env
```

不要提交 `.env`。它已经被 Git 忽略，仓库只提交 `.env.example` 作为配置说明。

Do not commit `.env`. It is ignored by Git; the repository only commits `.env.example` as configuration documentation.

### 环境变量速查 / Environment Variables

| 分组 / Group | 变量 / Variables |
| --- | --- |
| App and CORS | `APP_NAME`, `APP_API_PREFIX`, `APP_TIMEZONE`, `CORS_ORIGINS`, `BACKEND_PORT`, `FRONTEND_PORT`, `VITE_API_BASE_URL`, `VITE_API_PREFIX` |
| Demo PostgreSQL container | `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_HOST_PORT`, `POSTGRES_READONLY_USER`, `POSTGRES_READONLY_PASSWORD` |
| Backend database connection | `DATABASE_URL`, `PG_MAX_ROWS`, `PG_STATEMENT_TIMEOUT_MS`, `PG_SCHEMA_LIMIT` |
| Business rules | `BUSINESS_RULES_DIR`, `BUSINESS_RULE_MAX_FILE_BYTES`, `BUSINESS_RULE_MAX_RESULTS` |
| LLM provider | `LLM_PROVIDER`, `LLM_BASE_URL`, `LLM_MODEL`, `LLM_API_KEY`, `LLM_TIMEOUT_SECONDS` |

前端右侧配置面板也会显示同一组数据库和大模型配置。如果大模型配置缺失，后端仍可针对内置 `aiinfra` Schema 运行有限的本地演示回退逻辑；生产使用应配置真实的大模型服务。

The frontend configuration panel shows the same database and model fields. If the model config is missing, the backend can still run a limited local demo fallback for the bundled `aiinfra` schema; production use should configure a real model provider.
