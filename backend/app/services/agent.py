from __future__ import annotations

import json
import re
from typing import Any, Callable

from backend.app.models import AgentQueryRequest, AgentQueryResponse, TraceStep
from backend.app.services.llm import (
    LLMNotConfigured,
    chat_completion,
    generate_answer,
    generate_sql,
    is_llm_configured,
)
from backend.app.services.token_usage import begin_token_usage, finish_token_usage


DEFAULT_VALIDATION: dict[str, Any] = {
    "ok": False,
    "reason": "No SQL has been generated yet.",
    "normalized_sql": None,
    "limited_sql": None,
}

AGENT_TOOL_SPECS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "current_date_context",
            "description": "Get current date, timestamp, and current week boundaries for relative date questions.",
            "parameters": {
                "type": "object",
                "properties": {
                    "timezone_name": {
                        "type": "string",
                        "description": "Optional IANA timezone, for example Asia/Shanghai.",
                    }
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "business_rule_search",
            "description": "Search business metric definitions and calculation rules.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 20},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "pg_schema_overview",
            "description": "Return a compact overview of PostgreSQL tables and columns in the configured schema scope.",
            "parameters": {
                "type": "object",
                "properties": {
                    "limit": {"type": "integer", "minimum": 1, "maximum": 200},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "pg_describe_table",
            "description": "Describe one PostgreSQL table with columns, indexes, and table comments.",
            "parameters": {
                "type": "object",
                "properties": {
                    "schema": {"type": "string"},
                    "table": {"type": "string"},
                },
                "required": ["schema", "table"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "pg_validate_sql",
            "description": "Validate that a SQL statement is a single readonly PostgreSQL SELECT or WITH query.",
            "parameters": {
                "type": "object",
                "properties": {
                    "sql": {"type": "string"},
                    "max_rows": {"type": "integer", "minimum": 1, "maximum": 5000},
                },
                "required": ["sql"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "pg_query",
            "description": "Execute a guarded readonly PostgreSQL SELECT query and return tabular rows.",
            "parameters": {
                "type": "object",
                "properties": {
                    "sql": {"type": "string"},
                    "max_rows": {"type": "integer", "minimum": 1, "maximum": 5000},
                },
                "required": ["sql"],
            },
        },
    },
]


def run_agent_query(request: AgentQueryRequest) -> AgentQueryResponse:
    trace: list[TraceStep] = []
    usage_token = begin_token_usage()
    usage_finished = False

    try:
        if is_llm_configured():
            try:
                response = _run_tool_calling_agent(request, trace)
                usage = finish_token_usage(usage_token)
                usage_finished = True
                return response.model_copy(update={"token_usage": usage})
            except LLMNotConfigured as exc:
                _append_trace(trace, "llm_agent_loop", "warning", str(exc), {"mode": "tool_calling"})
            except Exception as exc:
                _append_trace(
                    trace,
                    "llm_agent_loop",
                    "warning",
                    f"Tool-calling agent loop failed; falling back to orchestrated mode: {exc}",
                    {"mode": "tool_calling"},
                )

        response = _run_orchestrated_agent(request, trace)
        usage = finish_token_usage(usage_token)
        usage_finished = True
        return response.model_copy(update={"token_usage": usage})
    except Exception:
        if not usage_finished:
            finish_token_usage(usage_token)
        raise


def _run_tool_calling_agent(request: AgentQueryRequest, trace: list[TraceStep]) -> AgentQueryResponse:
    language = _resolve_language(request)
    max_rows = request.max_rows or 200
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": _system_prompt(language)},
        {
            "role": "user",
            "content": (
                f"Question: {request.question}\n"
                f"Language: {language}\n"
                f"Max rows: {max_rows}\n"
                "Use MCP tools to inspect date context, business rules, schema, validate SQL, "
                "and query PostgreSQL. Final answer should summarize the readonly query result."
            ),
        },
    ]

    date_context: dict[str, Any] = {}
    rules: list[dict[str, Any]] = []
    schema: dict[str, Any] | None = None
    validation: dict[str, Any] = dict(DEFAULT_VALIDATION)
    result: dict[str, Any] | None = None
    sql = ""
    tool_call_count = 0

    for _ in range(8):
        assistant_message = chat_completion(messages=messages, tools=AGENT_TOOL_SPECS, tool_choice="auto")
        tool_calls = assistant_message.get("tool_calls") or []
        if not tool_calls:
            if tool_call_count == 0:
                raise RuntimeError("LLM returned a direct answer without calling MCP tools.")
            answer = str(assistant_message.get("content") or "").strip()
            if not answer:
                answer = _local_answer(
                    question=request.question,
                    language=language,
                    date_context=date_context,
                    result=result,
                    executed=result is not None,
                )
            return AgentQueryResponse(
                question=request.question,
                answer=answer,
                sql=sql,
                executed=result is not None,
                trace=trace,
                rules=rules,
                db_schema=schema,
                validation=validation,
                result=result,
            )

        messages.append(
            {
                "role": "assistant",
                "content": assistant_message.get("content"),
                "tool_calls": tool_calls,
            }
        )

        for tool_call in tool_calls:
            tool_call_count += 1
            function = tool_call.get("function") or {}
            name = str(function.get("name") or "")
            arguments = _parse_tool_arguments(function.get("arguments"))
            output = _call_mcp_tool(name, arguments)

            if name == "current_date_context" and isinstance(output, dict):
                date_context = output
            elif name == "business_rule_search" and isinstance(output, list):
                rules = output
            elif name == "pg_schema_overview" and isinstance(output, dict):
                schema = output
            elif name == "pg_validate_sql" and isinstance(output, dict):
                validation = output
                sql = str(arguments.get("sql") or sql)
            elif name == "pg_query" and isinstance(output, dict):
                result = output
                sql = str(arguments.get("sql") or sql)

            _append_trace(
                trace,
                f"mcp.{name}",
                "success",
                _tool_summary(name, output),
                {"arguments": arguments, "result": _preview(output)},
            )
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tool_call.get("id") or f"tool-{tool_call_count}",
                    "name": name,
                    "content": _json_text(output),
                }
            )

    answer = _local_answer(
        question=request.question,
        language=language,
        date_context=date_context,
        result=result,
        executed=result is not None,
    )
    _append_trace(trace, "llm_agent_loop", "warning", "Reached maximum Agent loop iterations.", {})
    return AgentQueryResponse(
        question=request.question,
        answer=answer,
        sql=sql,
        executed=result is not None,
        trace=trace,
        rules=rules,
        db_schema=schema,
        validation=validation,
        result=result,
    )


def _run_orchestrated_agent(request: AgentQueryRequest, trace: list[TraceStep]) -> AgentQueryResponse:
    language = _resolve_language(request)
    max_rows = request.max_rows or 200

    date_context = _safe_tool_call(trace, "current_date_context", {}) or {}
    rules = _safe_tool_call(trace, "business_rule_search", {"query": request.question, "limit": 8}) or []
    schema = _safe_tool_call(trace, "pg_schema_overview", {"limit": 80})
    if not isinstance(schema, dict):
        schema = None

    sql = _extract_sql(request.question)
    if sql:
        _append_trace(trace, "sql_generation", "success", "Used SQL supplied in the user message.", {"mode": "extract"})
    else:
        sql = _generate_sql(request, schema, rules if isinstance(rules, list) else [], date_context, trace)

    validation = _safe_tool_call(trace, "pg_validate_sql", {"sql": sql, "max_rows": max_rows})
    if not isinstance(validation, dict):
        validation = dict(DEFAULT_VALIDATION)

    result: dict[str, Any] | None = None
    executed = False
    if request.execute and validation.get("ok"):
        query_result = _safe_tool_call(trace, "pg_query", {"sql": sql, "max_rows": max_rows})
        if isinstance(query_result, dict):
            result = query_result
            executed = True

    answer = None
    try:
        answer = generate_answer(
            question=request.question,
            language=language,
            date_context=date_context if isinstance(date_context, dict) else {},
            sql=sql,
            result=result,
            rules=rules if isinstance(rules, list) else [],
        )
        if answer:
            _append_trace(trace, "llm_final_answer", "success", "Generated final answer with configured LLM.", {})
    except Exception as exc:
        _append_trace(trace, "llm_final_answer", "warning", str(exc), {})

    if not answer:
        answer = _local_answer(
            question=request.question,
            language=language,
            date_context=date_context if isinstance(date_context, dict) else {},
            result=result,
            executed=executed,
        )

    return AgentQueryResponse(
        question=request.question,
        answer=answer,
        sql=sql,
        executed=executed,
        trace=trace,
        rules=rules if isinstance(rules, list) else [],
        db_schema=schema,
        validation=validation,
        result=result,
    )


def _generate_sql(
    request: AgentQueryRequest,
    schema: dict[str, Any] | None,
    rules: list[dict[str, Any]],
    date_context: dict[str, Any],
    trace: list[TraceStep],
) -> str:
    try:
        generated = generate_sql(
            question=request.question,
            schema=schema,
            rules=rules,
            date_context=date_context,
        )
    except LLMNotConfigured as exc:
        _append_trace(trace, "sql_generation", "warning", str(exc), {"mode": "manual"})
        generated = None
    except Exception as exc:
        _append_trace(trace, "sql_generation", "warning", str(exc), {"mode": "llm"})
        generated = None

    if generated:
        _append_trace(trace, "sql_generation", "success", "Generated SQL with the configured LLM.", {"mode": "llm"})
        return _strip_markdown_sql(generated)

    demo_sql = _demo_sql_from_question(request.question, schema, date_context)
    if demo_sql:
        _append_trace(
            trace,
            "sql_generation",
            "success",
            "Generated SQL with the local demo fallback.",
            {"mode": "demo_fallback"},
        )
        return demo_sql

    _append_trace(
        trace,
        "sql_generation",
        "warning",
        "No LLM provider is configured; returning an editable starter query.",
        {"mode": "manual"},
    )
    return "SELECT 1 AS agent_ready"


def _safe_tool_call(trace: list[TraceStep], name: str, arguments: dict[str, Any]) -> Any:
    try:
        output = _call_mcp_tool(name, arguments)
        _append_trace(
            trace,
            f"mcp.{name}",
            "success",
            _tool_summary(name, output),
            {"arguments": arguments, "result": _preview(output)},
        )
        return output
    except Exception as exc:
        _append_trace(trace, f"mcp.{name}", "error", str(exc), {"arguments": arguments})
        return None


def _call_mcp_tool(name: str, arguments: dict[str, Any]) -> Any:
    registry = _mcp_tool_registry()
    if name not in registry:
        raise ValueError(f"Unknown MCP tool: {name}")
    return _json_safe(registry[name](**arguments))


def _mcp_tool_registry() -> dict[str, Callable[..., Any]]:
    from backend.app.mcp import server

    return {
        "current_date_context": server.current_date_context,
        "business_rule_search": server.business_rule_search,
        "pg_schema_overview": server.pg_schema_overview,
        "pg_describe_table": server.pg_describe_table,
        "pg_validate_sql": server.pg_validate_sql,
        "pg_query": server.pg_query,
    }


def _system_prompt(language: str) -> str:
    language_instruction = "Chinese" if language == "zh" else "English" if language == "en" else "the user's language"
    return (
        "You are a readonly business data Agent for PostgreSQL. "
        "You must use the MCP tools before answering data questions. "
        "For relative dates such as today, yesterday, this week, or latest day, call current_date_context first. "
        "Search business_rule_search for metric definitions. Inspect pg_schema_overview before writing SQL. "
        "Validate SQL with pg_validate_sql before pg_query. "
        "Only query through pg_query; it enforces a readonly SELECT/WITH policy. "
        f"Answer in {language_instruction}, concisely, and never invent data."
    )


def _parse_tool_arguments(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if not raw:
        return {}
    try:
        parsed = json.loads(str(raw))
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _append_trace(
    trace: list[TraceStep],
    name: str,
    status: str,
    summary: str,
    detail: dict[str, Any],
) -> None:
    trace.append(
        TraceStep(
            name=name,
            status=status,  # type: ignore[arg-type]
            summary=summary,
            detail=_json_safe(detail),
        )
    )


def _tool_summary(name: str, output: Any) -> str:
    if name == "current_date_context" and isinstance(output, dict):
        return f"Resolved today as {output.get('today')} in {output.get('timezone')}."
    if name == "business_rule_search" and isinstance(output, list):
        return f"Found {len(output)} matching business rule file(s)."
    if name == "pg_schema_overview" and isinstance(output, dict):
        return f"Loaded {output.get('table_count', 0)} table(s) from PostgreSQL."
    if name == "pg_validate_sql" and isinstance(output, dict):
        return "SQL passed readonly validation." if output.get("ok") else str(output.get("reason"))
    if name == "pg_query" and isinstance(output, dict):
        return f"Readonly query returned {output.get('row_count', 0)} row(s)."
    return "MCP tool call completed."


def _preview(value: Any) -> Any:
    if isinstance(value, dict):
        preview = dict(value)
        if "rows" in preview and isinstance(preview["rows"], list):
            preview["rows"] = preview["rows"][:3]
        if "tables" in preview and isinstance(preview["tables"], list):
            preview["tables"] = preview["tables"][:6]
        return preview
    if isinstance(value, list):
        return value[:6]
    return value


def _json_text(value: Any) -> str:
    return json.dumps(_json_safe(value), ensure_ascii=False)


def _json_safe(value: Any) -> Any:
    return json.loads(json.dumps(value, default=str, ensure_ascii=False))


def _extract_sql(question: str) -> str | None:
    lowered = question.strip().lower()
    if lowered.startswith("select ") or lowered.startswith("with "):
        return question.strip()

    marker = "```sql"
    if marker not in lowered:
        return None
    start = lowered.find(marker)
    content_start = start + len(marker)
    end = lowered.find("```", content_start)
    if end == -1:
        return None
    return question[content_start:end].strip()


def _strip_markdown_sql(sql: str) -> str:
    value = sql.strip()
    fenced = re.match(r"^```(?:sql)?\s*(.*?)\s*```$", value, flags=re.IGNORECASE | re.DOTALL)
    if fenced:
        return fenced.group(1).strip()
    return value


def _resolve_language(request: AgentQueryRequest) -> str:
    if request.language in {"zh", "en"}:
        return request.language
    return "zh" if re.search(r"[\u4e00-\u9fff]", request.question) else "en"


def _local_answer(
    *,
    question: str,
    language: str,
    date_context: dict[str, Any],
    result: dict[str, Any] | None,
    executed: bool,
) -> str:
    row_count = int(result.get("row_count", 0)) if isinstance(result, dict) else 0
    today = date_context.get("today", "unknown")
    week_start = date_context.get("week_start", "unknown")
    week_end = date_context.get("week_end", "unknown")

    if language == "zh":
        if not executed:
            return "还没有成功执行只读查询。请先配置 DATABASE_URL 和大模型，或检查生成 SQL 是否通过只读校验。"
        if row_count == 0:
            return f"已按只读查询执行，但没有返回数据。当前日期为 {today}，本周范围为 {week_start} 到 {week_end}。"
        return f"已完成只读查询，返回 {row_count} 行结果。当前日期为 {today}，本周范围为 {week_start} 到 {week_end}，明细见下方表格。"

    if not executed:
        return "No readonly query has completed. Configure DATABASE_URL and the LLM provider, or check SQL validation."
    if row_count == 0:
        return f"The readonly query completed but returned no rows. Today is {today}; this week is {week_start} to {week_end}."
    return f"The readonly query returned {row_count} row(s). Today is {today}; this week is {week_start} to {week_end}. See the table below."


def _demo_sql_from_question(
    question: str,
    schema: dict[str, Any] | None,
    date_context: dict[str, Any],
) -> str | None:
    if not _has_aiinfra_demo_tables(schema):
        return None

    text = question.lower()
    date_filter, include_date = _metric_date_filter(question, date_context)
    date_select = "  m.metric_date,\n" if include_date else ""
    date_group = "m.metric_date, " if include_date else ""
    date_order = "m.metric_date DESC, " if include_date else ""

    if any(term in question for term in ["总卡数", "卡数", "多少卡", "gpu数量", "gpu 数量"]) or any(
        term in text for term in ["total gpu", "gpu count", "card count", "inventory"]
    ):
        return (
            "SELECT\n"
            "  c.cluster_name,\n"
            "  n.gpu_model,\n"
            "  SUM(n.gpu_count) AS total_gpus,\n"
            "  SUM(CASE WHEN n.status = 'active' THEN n.gpu_count ELSE 0 END) AS active_gpus,\n"
            "  SUM(CASE WHEN n.status <> 'active' THEN n.gpu_count ELSE 0 END) AS unavailable_gpus\n"
            "FROM aiinfra.gpu_nodes n\n"
            "JOIN aiinfra.clusters c ON c.id = n.cluster_id\n"
            "GROUP BY c.cluster_name, n.gpu_model\n"
            "ORDER BY c.cluster_name, n.gpu_model"
        )

    if any(term in question for term in ["卡时使用率", "使用率", "利用率", "卡时"]) or any(
        term in text for term in ["utilization", "gpu-hour", "gpu hour", "card-hour", "card hour"]
    ):
        return (
            "SELECT\n"
            f"{date_select}"
            "  c.cluster_name,\n"
            "  m.gpu_model,\n"
            "  SUM(m.allocated_gpu_hours) AS allocated_gpu_hours,\n"
            "  SUM(m.idle_gpu_hours) AS idle_gpu_hours,\n"
            "  ROUND(\n"
            "    100 * SUM(m.allocated_gpu_hours) / NULLIF(SUM(m.allocated_gpu_hours + m.idle_gpu_hours), 0),\n"
            "    2\n"
            "  ) AS card_hour_utilization_pct,\n"
            "  ROUND(AVG(m.avg_gpu_utilization_pct), 2) AS avg_gpu_core_utilization_pct\n"
            "FROM aiinfra.daily_gpu_metrics m\n"
            "JOIN aiinfra.clusters c ON c.id = m.cluster_id\n"
            f"WHERE {date_filter}\n"
            f"GROUP BY {date_group}c.cluster_name, m.gpu_model\n"
            f"ORDER BY {date_order}card_hour_utilization_pct DESC"
        )

    if any(term in question for term in ["等待", "排队", "容量压力", "压力"]) or any(
        term in text for term in ["queue", "wait", "pressure", "capacity"]
    ):
        return (
            "SELECT\n"
            f"{date_select}"
            "  c.cluster_name,\n"
            "  m.gpu_model,\n"
            "  ROUND(AVG(m.queue_wait_minutes), 2) AS avg_queue_wait_minutes,\n"
            "  SUM(m.allocated_gpu_hours) AS allocated_gpu_hours,\n"
            "  SUM(m.idle_gpu_hours) AS idle_gpu_hours\n"
            "FROM aiinfra.daily_gpu_metrics m\n"
            "JOIN aiinfra.clusters c ON c.id = m.cluster_id\n"
            f"WHERE {date_filter}\n"
            f"GROUP BY {date_group}c.cluster_name, m.gpu_model\n"
            "HAVING AVG(m.queue_wait_minutes) >= 30\n"
            f"ORDER BY {date_order}avg_queue_wait_minutes DESC"
        )

    if any(term in question for term in ["成本", "花费", "费用", "单卡时"]) or any(
        term in text for term in ["cost", "spend", "price"]
    ):
        return (
            "SELECT\n"
            f"{date_select}"
            "  c.cluster_name,\n"
            "  m.gpu_model,\n"
            "  SUM(m.cost_usd) AS cost_usd,\n"
            "  SUM(m.allocated_gpu_hours) AS allocated_gpu_hours,\n"
            "  ROUND(SUM(m.cost_usd) / NULLIF(SUM(m.allocated_gpu_hours), 0), 2) AS cost_per_used_gpu_hour\n"
            "FROM aiinfra.daily_gpu_metrics m\n"
            "JOIN aiinfra.clusters c ON c.id = m.cluster_id\n"
            f"WHERE {date_filter}\n"
            f"GROUP BY {date_group}c.cluster_name, m.gpu_model\n"
            f"ORDER BY {date_order}cost_usd DESC"
        )

    if any(term in question for term in ["告警", "事件", "故障", "风险"]) or any(
        term in text for term in ["alert", "event", "incident", "failure", "risk"]
    ):
        return (
            "SELECT\n"
            "  c.cluster_name,\n"
            "  e.severity,\n"
            "  e.event_type,\n"
            "  e.message,\n"
            "  e.affected_gpus,\n"
            "  e.event_time\n"
            "FROM aiinfra.capacity_events e\n"
            "JOIN aiinfra.clusters c ON c.id = e.cluster_id\n"
            "WHERE e.resolved_at IS NULL\n"
            "ORDER BY\n"
            "  CASE e.severity WHEN 'critical' THEN 1 WHEN 'warning' THEN 2 ELSE 3 END,\n"
            "  e.event_time DESC"
        )

    return None


def _metric_date_filter(question: str, date_context: dict[str, Any]) -> tuple[str, bool]:
    text = question.lower()
    today = str(date_context.get("today") or "")
    week_start = str(date_context.get("week_start") or "")
    week_end = str(date_context.get("week_end") or "")

    if today and (any(term in question for term in ["今天", "今日"]) or "today" in text):
        return f"m.metric_date = DATE '{today}'", True

    if week_start and week_end and (
        any(term in question for term in ["本周", "这周", "这一周", "一周"])
        or "this week" in text
        or "current week" in text
        or "weekly" in text
    ):
        return f"m.metric_date BETWEEN DATE '{week_start}' AND DATE '{week_end}'", True

    return "m.metric_date = (SELECT MAX(metric_date) FROM aiinfra.daily_gpu_metrics)", False


def _has_aiinfra_demo_tables(schema: dict[str, Any] | None) -> bool:
    tables = schema.get("tables") if schema else None
    if not isinstance(tables, list):
        return False
    names = {
        f"{item.get('schema')}.{item.get('table')}"
        for item in tables
        if isinstance(item, dict)
    }
    return {
        "aiinfra.clusters",
        "aiinfra.gpu_nodes",
        "aiinfra.daily_gpu_metrics",
        "aiinfra.capacity_events",
    }.issubset(names)
