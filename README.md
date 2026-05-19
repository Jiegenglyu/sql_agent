# sql_agent

可追踪的中英双语 PostgreSQL 业务数据 Agent。用户可以用中文或英文通过 MCP 提问，后端 Agent 会统一协调读取业务规则原文、读取数据库结构、调用大模型生成 SQL、校验并执行受保护的 `SELECT` 查询，最后返回业务答案、SQL、来源表、执行链路和结果表。

Traceable bilingual business data Agent for PostgreSQL. Users can ask questions in Chinese or English through MCP; the backend Agent coordinates business-rule context, schema inspection, model-generated SQL, readonly validation, guarded execution, then returns the answer, SQL, source tables, trace, and result rows.

## 项目简介 / Overview

`sql_agent` 面向需要“用自然语言查业务数据库”的场景。它把一次 MCP 查询拆成可审计步骤：鉴权、读取业务规则 Markdown、读取 Schema、生成 SQL、只读校验、数据库查询和回答生成。

`sql_agent` is built for business data workflows where users query databases with natural language. It makes the MCP-to-SQL path auditable through authentication, Markdown business-rule context, schema inspection, SQL generation, readonly validation, query execution, and answer generation.

## 功能特性 / Features

- 业务规则原文驱动：Agent 读取 Markdown 规则作为 SQL 生成上下文，本地代码不硬编码复杂业务解析。
- Business-rule-context driven: the Agent reads Markdown rules as SQL-generation context instead of hard-coding complex business parsing locally.
- 资源池和卡型号联合查询：内置 `resource_pools` 和 `gpu_card_models` 两张演示业务表，通过 `pool_type` 支持 JOIN。
- Resource pool and card-model joins: bundled demo tables `resource_pools` and `gpu_card_models` join through `pool_type`.
- 明确错误状态：查询失败直接返回 `error`，区分鉴权失败、模型失败、SQL 错误、查询超时和没有数据。
- Explicit error status: failures return `error` directly, including auth failures, model errors, SQL errors, query timeouts, and no-data results.
- MCP 看板：前端展示调用方、鉴权状态、执行链路、SQL、来源表、配置和结构化结果。
- MCP dashboard: the frontend shows caller, auth state, trace, SQL, source tables, config, and structured rows.

## 架构 / Architecture

- 后端 API / Backend API: FastAPI service in `backend/app/main.py`.
- 南向 MCP 工具 / Southbound MCP tools: internal PostgreSQL and business rule tools in `backend/app/mcp/server.py`.
- 北向 MCP 接口 / Northbound MCP interface: public question-answer tool in `backend/app/mcp/public_server.py`.
- PostgreSQL 访问 / PostgreSQL access: read-only SQL guard plus PostgreSQL read-only transaction execution.
- 业务规则 / Business rules: local folder context/list/search/read limited to `backend/business_rules`.
- 前端 / Frontend: Vite React MCP dashboard in `frontend`.

## 安全边界 / Security Boundaries

- PostgreSQL 只接受单条 `SELECT` 或只读 `WITH` 语句。
- PostgreSQL execution accepts only one `SELECT` or read-only `WITH` statement.
- 生成 SQL 会被服务端自动加上 `LIMIT`。
- Generated SQL is wrapped with a server-side `LIMIT`.
- PostgreSQL 会话使用 `SET TRANSACTION READ ONLY`。
- PostgreSQL sessions use `SET TRANSACTION READ ONLY`.
- Agent 通过 MCP 工具处理日期上下文、业务规则、Schema、SQL 校验和查询执行。
- The Agent calls MCP tools for date context, business rules, schema, SQL validation, and query execution.
- 业务规则工具不调用 shell 命令，只能在配置目录内 list/search/read，并拒绝绝对路径、目录逃逸、不支持的扩展名、符号链接和超大文件。
- Business rule tools do not use shell commands, are limited to list/search/read inside the configured directory, and reject absolute paths, path escapes, unsupported extensions, symlinks, and oversized files.
- 本地密钥只放在 `.env`，该文件已被 Git 忽略。
- Local secrets live only in `.env`, which is ignored by Git.
- 北向 MCP 工具必须传 `api_key`，有效 key 从 `MCP_API_KEYS` 读取。
- Northbound MCP tools require an `api_key`; valid keys are read from `MCP_API_KEYS`.

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

启动内部南向 MCP server。

Start the internal southbound MCP server.

```bash
make mcp
# or: uv run python -m backend.app.mcp.server
```

启动北向 MCP server。这个服务只暴露面向外部 Agent 的公开能力，不会向外部 MCP client 注册 `pg_query`、`pg_describe_table`、`business_rule_read` 等数据库和规则工具。

Start the northbound MCP server. This server exposes only public Agent-facing capabilities; it does not register `pg_query`, `pg_describe_table`, `business_rule_read`, or other database/rule tools to external MCP clients.

```bash
make public-mcp
# standard stateful Streamable HTTP endpoint: http://127.0.0.1:8001/mcp
```

北向 MCP 暴露两个工具和一个 resource：

The northbound MCP exposes two tools and one resource:

- `ask_agent`: 提问并返回 `status`、`answer`、`result.columns`、`result.rows`、`result.sql`、`source_tables`、`trace` 和 `error`。
- `describe_capabilities`: 根据当前业务规则返回“能查什么”的公开摘要；如果配置了 LLM，会优先使用 LLM 压缩总结，失败时回退到本地规则摘要。
- `capabilities://sql-agent`: 同一份能力摘要的 MCP resource，方便外部 agent 在选择工具前读取。

外部用户入口统一使用 HTTP remote MCP。`mcp.json` 是内部南向工具配置，不要作为外部用户入口。

External clients should use HTTP remote MCP. `mcp.json` is the internal southbound tools config and should not be used as the external user entrypoint.

### 外部 Agent 接入 / External Agent MCP Clients

先启动北向 MCP 服务。默认只监听本机 `127.0.0.1`，工具调用必须携带 `api_key`。

Start the northbound MCP server first. It binds to local `127.0.0.1` by default and tool calls must include `api_key`.

```bash
make public-mcp
```

#### Claude Code

Claude Code 推荐使用 HTTP MCP：

Claude Code should use HTTP MCP:

```bash
PUBLIC_MCP_HOST=0.0.0.0 PUBLIC_MCP_STATELESS_HTTP=false make public-mcp

claude mcp add \
  --transport http \
  --scope user \
  sql_agent \
  http://127.0.0.1:8001/mcp

claude mcp list
claude mcp get sql_agent
```

在 Claude Code 里使用 `/mcp` 检查连接。新加 MCP 后，如果当前会话没有看到新工具，退出并重新进入 `claude`。

Inside Claude Code, use `/mcp` to inspect the connection. If a running session does not see newly added tools, exit and start `claude` again.

示例提示：

Example prompts:

```text
调用 sql_agent 的 describe_capabilities，api_key=sk-1234，language=zh
调用 sql_agent 的 ask_agent，api_key=sk-1234，caller=claude-code，question 是：Xlarge 是什么卡？language 是 zh
读取 @sql_agent:capabilities://sql-agent，然后用 sql_agent 回答我能查哪些业务问题
```

#### OpenClaw

OpenClaw 的 `openclaw mcp set` 用于保存外部 MCP server 定义，供 OpenClaw 启动或配置的运行时使用：

OpenClaw uses `openclaw mcp set` to save outbound MCP server definitions for runtimes it launches or configures:

```bash
openclaw mcp set sql_agent '{"url":"http://127.0.0.1:8001/mcp","transport":"streamable-http"}'
openclaw mcp list
openclaw mcp show sql_agent --json
```

#### OpenCode

OpenCode 在 `opencode.json` 的 `mcp` 字段下配置 MCP server。远程 HTTP 配置如下：

OpenCode configures MCP servers under the `mcp` field in `opencode.json`. For remote HTTP:

```json
{
  "$schema": "https://opencode.ai/config.json",
  "mcp": {
    "sql_agent": {
      "type": "remote",
      "url": "http://127.0.0.1:8001/mcp",
      "enabled": true
    }
  }
}
```

在 OpenCode 中提示模型使用 `sql_agent`：

Prompt OpenCode to use `sql_agent`:

```text
先用 sql_agent 的 describe_capabilities 看能查什么，然后查询 Xlarge 是什么卡。调用工具时传 api_key。
```

如果外部 agent 不在本机运行，`127.0.0.1` 会指向 agent 所在环境。此时需要把北向 MCP 绑定到可访问地址，并在受信网络或反向代理鉴权后使用：

If the external agent does not run on the same machine, `127.0.0.1` points to the agent's own environment. Bind the northbound MCP to a reachable address and put it behind a trusted network or authenticated reverse proxy:

```bash
PUBLIC_MCP_HOST=0.0.0.0 make public-mcp
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

- `aiinfra.resource_pools`
- `aiinfra.gpu_card_models`

两张表通过 `pool_type` 关联。业务规则写在 `backend/business_rules/resource_pools.md` 和 `backend/business_rules/gpu_card_models.md`，Agent 会读取规则原文后让模型生成 SQL。

The two tables join through `pool_type`. Business rules live in `backend/business_rules/resource_pools.md` and `backend/business_rules/gpu_card_models.md`; the Agent reads those Markdown files before asking the model to generate SQL.

示例问题 / Example questions:

| 中文 | English |
| --- | --- |
| Xlarge 是什么卡？ | What GPU card does Xlarge use? |
| A100 有哪些资源池？ | Which resource pools use A100? |
| 按卡型号统计资源池容量。 | Summarize resource pool capacity by GPU model. |
| cn-east 区域有哪些资源池？ | Which resource pools are in cn-east? |
| QuantumPool 是什么卡？ | What card does QuantumPool use? |

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
| Northbound MCP | `PUBLIC_MCP_TRANSPORT`, `PUBLIC_MCP_HOST`, `PUBLIC_MCP_PORT`, `PUBLIC_MCP_PATH`, `PUBLIC_MCP_STATELESS_HTTP`, `MCP_API_KEYS` |
| Demo PostgreSQL container | `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_HOST_PORT`, `POSTGRES_READONLY_USER`, `POSTGRES_READONLY_PASSWORD` |
| Backend database connection | `DATABASE_URL`, `PG_MAX_ROWS`, `PG_STATEMENT_TIMEOUT_MS`, `PG_SCHEMA_LIMIT`, `PG_SCHEMAS` |
| Business rules and Agent debug | `BUSINESS_RULES_DIR`, `BUSINESS_RULE_MAX_FILE_BYTES`, `BUSINESS_RULE_MAX_RESULTS`, `AGENT_VERBOSE_DEBUG`, `AGENT_DEBUG_LOG_PATH` |
| LLM provider | `LLM_PROVIDER`, `LLM_BASE_URL`, `LLM_MODEL`, `LLM_API_KEY`, `LLM_TIMEOUT_SECONDS` |

前端看板会显示同一组数据库、大模型和 MCP 鉴权配置。`PG_SCHEMAS` 为空时读取全部非系统 Schema；填写 `aiinfra,public` 这类逗号分隔值时，Agent 的 Schema 概览会限定到这些 Schema。大模型配置缺失或调用失败时，查询直接返回 `llm_error`，不会使用本地 SQL 降级。

The frontend dashboard shows the same database, model, and MCP auth fields. Leave `PG_SCHEMAS` empty to read all non-system schemas; set comma-separated values such as `aiinfra,public` to scope the Agent schema overview. If the model config is missing or model calls fail, queries return `llm_error` directly; there is no local SQL fallback.
