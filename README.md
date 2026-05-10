# sql_agent

Traceable bilingual business data Agent for PostgreSQL. Users ask in Chinese or English; the backend Agent uses readonly MCP tools to resolve dates, retrieve business rules, inspect schema, execute guarded SELECT queries, and return a business answer plus a result table.

## Architecture

- Backend API: FastAPI service in `backend/app/main.py`.
- MCP tools: PostgreSQL and business rule tools in `backend/app/mcp/server.py`.
- PostgreSQL access: read-only SQL guard plus PostgreSQL read-only transaction execution.
- Business rules: local folder search limited to `backend/business_rules`.
- Frontend: Vite React business query console in `frontend`, with Chinese/English switching.

## Security Boundaries

- PostgreSQL execution accepts only one `SELECT` or read-only `WITH` statement.
- Generated SQL is wrapped with a server-side `LIMIT`.
- PostgreSQL sessions use `SET TRANSACTION READ ONLY`.
- The Agent calls MCP tools for date context, business rules, schema, SQL validation, and PG query execution.
- Business rule search does not use shell commands.
- Business rule file access rejects absolute paths, path escapes, unsupported extensions, symlinks, and oversized files.
- Secrets live in `.env`, which is ignored by Git.

## Local Setup

```bash
uv sync --dev
cp .env.example .env
```

The project pins Python through `.python-version` and uses `uv.lock` for repeatable dependency resolution.

Install frontend dependencies:

```bash
cd frontend
npm install
```

## Run

Demo PostgreSQL:

```bash
make db-up
```

Backend:

```bash
make backend
# or: uv run uvicorn backend.app.main:app --reload --host 0.0.0.0 --port 8000
```

Frontend:

```bash
make frontend
```

MCP server:

```bash
make mcp
# or: uv run python -m backend.app.mcp.server
```

Tests:

```bash
make test
# or: uv run python -m unittest discover backend/tests
```

Reset demo data:

```bash
make db-reset
```

The demo PostgreSQL service uses database `circle_demo` for now, but the business schema is `aiinfra`.
The AI infra demo includes:

- `aiinfra.clusters`
- `aiinfra.gpu_nodes`
- `aiinfra.teams`
- `aiinfra.workloads`
- `aiinfra.gpu_allocations`
- `aiinfra.daily_gpu_metrics`
- `aiinfra.capacity_events`

Useful demo questions:

- `今天的卡时使用率多少？`
- `这一周的卡时使用率多少？`
- `现在 AI infra 总卡数是多少？`
- `最新一天各集群的卡时使用率是多少？`
- `哪些集群有容量压力？`
- `最新一天单卡时成本是多少？`
- `当前未解决的容量告警有哪些？`

## Configuration

All local configuration belongs in `.env`. Start from the documented example and then replace every `change-me` value:

```bash
cp .env.example .env
```

Do not commit `.env`; it is ignored by Git. The committed `.env.example` documents every required value:

- App and CORS settings: `APP_NAME`, `APP_API_PREFIX`, `APP_TIMEZONE`, `CORS_ORIGINS`, `BACKEND_PORT`, `FRONTEND_PORT`, `VITE_API_BASE_URL`, `VITE_API_PREFIX`.
- Demo PostgreSQL container: `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_HOST_PORT`, `POSTGRES_READONLY_USER`, `POSTGRES_READONLY_PASSWORD`.
- Backend database connection: `DATABASE_URL`, `PG_MAX_ROWS`, `PG_STATEMENT_TIMEOUT_MS`, `PG_SCHEMA_LIMIT`.
- Business rules: `BUSINESS_RULES_DIR`, `BUSINESS_RULE_MAX_FILE_BYTES`, `BUSINESS_RULE_MAX_RESULTS`.
- LLM provider: `LLM_PROVIDER`, `LLM_BASE_URL`, `LLM_MODEL`, `LLM_API_KEY`, `LLM_TIMEOUT_SECONDS`.

The frontend shows the same required model fields in the right-side configuration panel. If these are missing, the backend still runs a limited local demo fallback for the bundled `aiinfra` schema, but production use should configure a real model.
