import json
from queue import Queue
from threading import Thread
from typing import Any, Iterator

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from starlette.concurrency import run_in_threadpool

from backend.app.config import get_settings
from backend.app.models import (
    AgentQueryRequest,
    AgentQueryResponse,
    ConfigTestResponse,
    HealthResponse,
    RuntimeConfigResponse,
    RuntimeConfigUpdate,
    RuleSearchResponse,
    SchemaMetadataResponse,
    SqlExecuteRequest,
    SqlExecuteResponse,
    SqlValidationRequest,
    SqlValidationResponse,
)
from backend.app.services.agent import run_agent_query
from backend.app.services.business_rules import BusinessRuleError, search_rules
from backend.app.services.llm import is_llm_configured
from backend.app.services.postgres import DatabaseError, collect_schema_metadata, execute_select, preview_table, schema_overview
from backend.app.services.runtime_config import (
    RuntimeConfigError,
    read_runtime_config,
    test_database_config,
    test_llm_config,
    update_runtime_config,
)
from backend.app.services.sql_guard import validate_select_sql
from backend.app.services.token_usage import get_total_token_usage


settings = get_settings()
api_prefix = settings.api_prefix

app = FastAPI(title=settings.app_name)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    settings = get_settings()
    return HealthResponse(
        status="ok",
        database_configured=bool(settings.database_url),
        llm_configured=is_llm_configured(),
        llm_provider=settings.llm_provider,
        llm_model=settings.llm_model,
        app_timezone=settings.app_timezone,
        business_rules_dir=str(settings.business_rules_dir),
        agent_verbose_debug=settings.agent_verbose_debug,
        token_usage=get_total_token_usage(),
    )


@app.get(f"{api_prefix}/config", response_model=RuntimeConfigResponse)
def api_config_get() -> RuntimeConfigResponse:
    return RuntimeConfigResponse(**read_runtime_config())


@app.put(f"{api_prefix}/config", response_model=RuntimeConfigResponse)
def api_config_update(request: RuntimeConfigUpdate) -> RuntimeConfigResponse:
    try:
        return RuntimeConfigResponse(**update_runtime_config(request))
    except RuntimeConfigError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post(f"{api_prefix}/config/test/database", response_model=ConfigTestResponse)
def api_config_test_database(request: RuntimeConfigUpdate) -> ConfigTestResponse:
    try:
        return ConfigTestResponse(**test_database_config(request))
    except RuntimeConfigError as exc:
        return ConfigTestResponse(ok=False, message=str(exc))


@app.post(f"{api_prefix}/config/test/llm", response_model=ConfigTestResponse)
def api_config_test_llm(request: RuntimeConfigUpdate) -> ConfigTestResponse:
    try:
        return ConfigTestResponse(**test_llm_config(request))
    except RuntimeConfigError as exc:
        return ConfigTestResponse(ok=False, message=str(exc))


@app.get(f"{api_prefix}/rules/search", response_model=RuleSearchResponse)
def api_rule_search(q: str = Query(min_length=1, max_length=500)) -> RuleSearchResponse:
    try:
        return RuleSearchResponse(query=q, results=search_rules(q))
    except BusinessRuleError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get(f"{api_prefix}/schema")
def api_schema(schema: list[str] | None = Query(default=None)) -> dict:
    try:
        return schema_overview(schemas=schema)
    except DatabaseError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.get(f"{api_prefix}/schema/metadata", response_model=SchemaMetadataResponse)
async def api_schema_metadata(
    limit: int | None = Query(default=None, ge=1, le=500),
    schema: list[str] | None = Query(default=None),
) -> SchemaMetadataResponse:
    try:
        metadata = await run_in_threadpool(collect_schema_metadata, limit=limit, schemas=schema)
    except DatabaseError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return SchemaMetadataResponse(**metadata)


@app.get(f"{api_prefix}/schema/table-preview", response_model=SqlExecuteResponse)
async def api_table_preview(
    schema: str = Query(min_length=1, max_length=300),
    table: str = Query(min_length=1, max_length=300),
    limit: int = Query(default=10, ge=1, le=100),
) -> SqlExecuteResponse:
    try:
        result = await run_in_threadpool(preview_table, schema, table, max_rows=limit)
    except (DatabaseError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return SqlExecuteResponse(**result)


@app.post(f"{api_prefix}/sql/validate", response_model=SqlValidationResponse)
def api_sql_validate(request: SqlValidationRequest) -> SqlValidationResponse:
    settings = get_settings()
    validation = validate_select_sql(request.sql, max_rows=request.max_rows or settings.pg_max_rows)
    return SqlValidationResponse(**validation)


@app.post(f"{api_prefix}/sql/execute", response_model=SqlExecuteResponse)
def api_sql_execute(request: SqlExecuteRequest) -> SqlExecuteResponse:
    try:
        result = execute_select(request.sql, max_rows=request.max_rows)
    except (DatabaseError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return SqlExecuteResponse(**result)


@app.post(f"{api_prefix}/agent/query", response_model=AgentQueryResponse)
def api_agent_query(request: AgentQueryRequest) -> AgentQueryResponse:
    return run_agent_query(request)


@app.post(f"{api_prefix}/agent/query/stream")
def api_agent_query_stream(request: AgentQueryRequest) -> StreamingResponse:
    return StreamingResponse(
        _agent_query_event_stream(request),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


def _agent_query_event_stream(request: AgentQueryRequest) -> Iterator[str]:
    events: Queue[dict[str, Any] | None] = Queue()

    def on_trace(step) -> None:
        events.put(
            {
                "type": "trace",
                "step": step.model_dump(mode="json"),
            }
        )

    def run_query() -> None:
        try:
            response = run_agent_query(request, on_trace=on_trace)
            events.put(
                {
                    "type": "final",
                    "response": response.model_dump(mode="json", by_alias=True),
                }
            )
        except Exception as exc:
            events.put({"type": "error", "message": str(exc)})
        finally:
            events.put(None)

    Thread(target=run_query, daemon=True).start()

    while True:
        event = events.get()
        if event is None:
            break

        event_type = str(event.get("type") or "message")
        data = {key: value for key, value in event.items() if key != "type"}
        yield f"event: {event_type}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"
