from __future__ import annotations

from contextvars import ContextVar
from datetime import datetime, timezone
import json
import logging
import re
from pathlib import Path
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


LOGGER = logging.getLogger("sql_agent.agent")
TraceCallback = Callable[[TraceStep], None]
_TRACE_CALLBACK: ContextVar[TraceCallback | None] = ContextVar("agent_trace_callback", default=None)

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
            "name": "business_rule_resolve",
            "description": (
                "Resolve which table-scoped business rule files apply to the user question, "
                "including mandatory fixed logic, matched business logic sections, selected tables, "
                "confidence, and whether clarification is required."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 10},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "business_rule_search",
            "description": "Search business metric definitions and calculation rules across the configured rule directory.",
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
            "name": "business_rule_list",
            "description": "List available business rule files when choosing which rule document to inspect.",
            "parameters": {
                "type": "object",
                "properties": {},
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "business_rule_read",
            "description": (
                "Read a selected business rule file or line range after search identifies the relevant document. "
                "Use the relative path returned by business_rule_search or business_rule_list."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "start_line": {
                        "type": "integer",
                        "minimum": 1,
                        "description": "Optional 1-based start line for reading a focused rule section.",
                    },
                    "end_line": {
                        "type": "integer",
                        "minimum": 1,
                        "description": "Optional 1-based end line for reading a focused rule section.",
                    },
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "pg_schema_overview",
            "description": (
                "Return a compact overview of PostgreSQL tables and columns in the configured schema scope. "
                "Use only as a legacy fallback when structured business-rule routing cannot select tables."
            ),
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


def run_agent_query(request: AgentQueryRequest, on_trace: TraceCallback | None = None) -> AgentQueryResponse:
    trace: list[TraceStep] = []
    usage_token = begin_token_usage()
    usage_finished = False
    trace_callback_token = _TRACE_CALLBACK.set(on_trace)

    try:
        if is_llm_configured():
            try:
                response = _run_tool_calling_agent(request, trace)
                usage = finish_token_usage(usage_token)
                usage_finished = True
                response = response.model_copy(update={"token_usage": usage})
                _log_agent_debug("agent.final", response.model_dump(mode="json", by_alias=True))
                return response
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
        response = response.model_copy(update={"token_usage": usage})
        _log_agent_debug("agent.final", response.model_dump(mode="json", by_alias=True))
        return response
    except Exception:
        if not usage_finished:
            finish_token_usage(usage_token)
        _log_agent_debug(
            "agent.error",
            {"question": request.question, "trace": [step.model_dump(mode="json") for step in trace]},
        )
        raise
    finally:
        _TRACE_CALLBACK.reset(trace_callback_token)


def _run_tool_calling_agent(request: AgentQueryRequest, trace: list[TraceStep]) -> AgentQueryResponse:
    language = _resolve_language(request)
    max_rows = request.max_rows or 200
    prepared = _prepare_query_context(request, trace, language=language)
    if prepared.get("clarification_response"):
        return prepared["clarification_response"]

    date_context = prepared["date_context"]
    rules = prepared["rules"]
    schema = prepared["schema"]
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": _system_prompt(language)},
        {
            "role": "user",
            "content": (
                f"Question: {request.question}\n"
                f"Language: {language}\n"
                f"Max rows: {max_rows}\n"
                "Resolved date context:\n"
                f"{_json_text(date_context)}\n"
                "Selected business rules:\n"
                f"{_json_text(rules)}\n"
                "Selected PostgreSQL table metadata:\n"
                f"{_json_text(schema or {})}\n"
                "Use only the selected table metadata unless you must ask for clarification. "
                "Validate SQL and query PostgreSQL through MCP tools. "
                "Final answer should summarize the readonly query result."
            ),
        },
    ]

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

            if name == "business_rule_search" and isinstance(output, list):
                rules = output
                _append_trace(
                    trace,
                    f"mcp.{name}",
                    "success",
                    _tool_summary(name, output),
                    {"arguments": arguments, "result": _preview(output)},
                )
                rules = _read_relevant_business_rules(trace, rules)
                output = rules
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call.get("id") or f"tool-{tool_call_count}",
                        "name": name,
                        "content": _json_text(output),
                    }
                )
                continue

            if name == "current_date_context" and isinstance(output, dict):
                date_context = output
            elif name == "business_rule_resolve" and isinstance(output, dict):
                rules = _rules_from_resolve(output)
            elif name == "business_rule_read" and isinstance(output, dict):
                rules = _merge_rule_read_result(rules, output)
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

    prepared = _prepare_query_context(request, trace, language=language)
    if prepared.get("clarification_response"):
        return prepared["clarification_response"]
    date_context = prepared["date_context"]
    rules = prepared["rules"]
    schema = prepared["schema"]

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
        sql = _strip_markdown_sql(generated)
        _append_trace(
            trace,
            "sql_generation",
            "success",
            "Generated SQL with the configured LLM.",
            {"mode": "llm", "sql": sql},
        )
        return sql

    demo_sql = _demo_sql_from_question(request.question, schema, date_context)
    if demo_sql:
        _append_trace(
            trace,
            "sql_generation",
            "success",
            "Generated SQL with the local demo fallback.",
            {"mode": "demo_fallback", "sql": demo_sql},
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


def _prepare_query_context(
    request: AgentQueryRequest,
    trace: list[TraceStep],
    *,
    language: str,
) -> dict[str, Any]:
    date_context = _safe_tool_call(trace, "current_date_context", {}) or {}
    if not isinstance(date_context, dict):
        date_context = {}

    resolve_result = _safe_tool_call(
        trace,
        "business_rule_resolve",
        {"query": request.question, "limit": 3},
    )
    if not isinstance(resolve_result, dict):
        resolve_result = {}

    if resolve_result.get("clarification_required"):
        answer = _clarification_answer(resolve_result, language=language)
        _append_trace(
            trace,
            "clarification",
            "warning",
            "Question is ambiguous; asking the user to choose a business meaning before querying.",
            {"resolve": _preview(resolve_result)},
        )
        return {
            "date_context": date_context,
            "rules": _rules_from_resolve(resolve_result),
            "schema": None,
            "clarification_response": AgentQueryResponse(
                question=request.question,
                answer=answer,
                sql="",
                executed=False,
                trace=trace,
                rules=_rules_from_resolve(resolve_result),
                db_schema=None,
                validation=dict(DEFAULT_VALIDATION),
                result=None,
            ),
        }

    if resolve_result.get("reason") == "no_structured_rules":
        return _legacy_query_context(request, trace, date_context)

    rules = _rules_from_resolve(resolve_result)
    schema = _schema_for_selected_tables(trace, resolve_result)
    if not schema and not rules:
        return _legacy_query_context(request, trace, date_context)

    return {
        "date_context": date_context,
        "rules": rules,
        "schema": schema,
        "clarification_response": None,
    }


def _legacy_query_context(
    request: AgentQueryRequest,
    trace: list[TraceStep],
    date_context: dict[str, Any],
) -> dict[str, Any]:
    rules = _safe_tool_call(trace, "business_rule_search", {"query": request.question, "limit": 8}) or []
    if isinstance(rules, list):
        rules = _read_relevant_business_rules(trace, rules)
    schema = _safe_tool_call(trace, "pg_schema_overview", {"limit": 80})
    if not isinstance(schema, dict):
        schema = None
    return {
        "date_context": date_context,
        "rules": rules if isinstance(rules, list) else [],
        "schema": schema,
        "clarification_response": None,
    }


def _rules_from_resolve(resolve_result: dict[str, Any]) -> list[dict[str, Any]]:
    candidates = resolve_result.get("candidates")
    if not isinstance(candidates, list):
        return []
    rules: list[dict[str, Any]] = []
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        rule = dict(candidate)
        if rule.get("fixed_logic"):
            fixed_content = str(rule.get("fixed_logic") or "").strip()
            matched_content = _matched_sections_text(rule)
            rule["content"] = "\n\n".join(
                item
                for item in [
                    "### 固定查询逻辑 ###\n" + fixed_content if fixed_content else "",
                    "### 命中业务逻辑 ###\n" + matched_content if matched_content else "",
                ]
                if item
            )
        rules.append(rule)
    return rules


def _matched_sections_text(rule: dict[str, Any]) -> str:
    sections = rule.get("matched_sections")
    if not isinstance(sections, list):
        return ""
    chunks: list[str] = []
    for section in sections:
        if not isinstance(section, dict):
            continue
        title = str(section.get("title") or "业务逻辑").strip()
        content = str(section.get("content") or "").strip()
        if title or content:
            chunks.append(f"## {title}\n{content}".strip())
    return "\n\n".join(chunks)


def _schema_for_selected_tables(trace: list[TraceStep], resolve_result: dict[str, Any]) -> dict[str, Any] | None:
    selected = resolve_result.get("selected_tables")
    if not isinstance(selected, list) or not selected:
        return None

    tables: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for item in selected:
        if not isinstance(item, dict):
            continue
        table = str(item.get("table") or "").strip()
        schema = _resolve_selected_schema(item)
        if not table or not schema:
            continue
        key = (schema, table)
        if key in seen:
            continue
        seen.add(key)
        metadata = _safe_tool_call(trace, "pg_describe_table", {"schema": schema, "table": table})
        if isinstance(metadata, dict):
            metadata["selection_role"] = item.get("role")
            metadata["selection_reason"] = item.get("reason")
            metadata["business_rule_path"] = item.get("source_path")
            tables.append(metadata)

    if not tables:
        return None
    schemas = sorted({str(item.get("schema")) for item in tables if item.get("schema")})
    return {
        "tables": tables,
        "table_count": len(tables),
        "failed_count": sum(1 for item in tables if item.get("error")),
        "schemas": schemas,
        "selected_by": "business_rule_resolve",
    }


def _resolve_selected_schema(item: dict[str, Any]) -> str | None:
    schema = item.get("schema")
    if schema:
        return str(schema)
    try:
        from backend.app.config import get_settings

        schemas = get_settings().pg_schemas
        if len(schemas) == 1:
            return schemas[0]
    except Exception:
        return None
    return None


def _clarification_answer(resolve_result: dict[str, Any], *, language: str) -> str:
    options = resolve_result.get("options")
    if not isinstance(options, list):
        options = []
    if language == "en":
        if not options:
            return (
                "I do not have enough business context to choose the right table or metric yet. "
                "Please specify the metric, business object, time range, or grouping dimension."
            )
        lines = ["I need one clarification before querying. I understood the request as possibly referring to:"]
        for index, option in enumerate(options, start=1):
            lines.append(f"{index}. {option.get('label')}: {option.get('table')}")
        lines.append("Which one do you want to query?")
        return "\n".join(lines)

    if not options:
        return "我还不能确定要查哪张表或哪个指标。请补充具体指标、业务对象、时间范围或分组维度。"
    lines = ["我需要先澄清一下。我理解这个问题可能指以下几类："]
    for index, option in enumerate(options, start=1):
        lines.append(f"{index}. {option.get('label')}：{option.get('table')}")
    lines.append("你想看哪一种？")
    return "\n".join(lines)


def _read_relevant_business_rules(
    trace: list[TraceStep],
    rules: list[Any],
    *,
    max_files: int = 3,
    context_before: int = 3,
    context_after: int = 10,
) -> list[dict[str, Any]]:
    expanded: list[dict[str, Any]] = []
    for index, item in enumerate(rules):
        if not isinstance(item, dict):
            continue
        rule = dict(item)
        path = str(rule.get("path") or "")
        if not path or index >= max_files:
            expanded.append(rule)
            continue

        arguments: dict[str, Any] = {"path": path}
        snippet_line = _first_rule_snippet_line(rule)
        if snippet_line is not None:
            arguments["start_line"] = max(1, snippet_line - context_before)
            arguments["end_line"] = snippet_line + context_after

        read_result = _safe_tool_call(trace, "business_rule_read", arguments)
        if isinstance(read_result, dict):
            expanded.append(_merge_rule_context(rule, read_result))
        else:
            expanded.append(rule)
    return expanded


def _first_rule_snippet_line(rule: dict[str, Any]) -> int | None:
    snippets = rule.get("snippets")
    if not isinstance(snippets, list):
        return None
    for snippet in snippets:
        if not isinstance(snippet, dict):
            continue
        try:
            line = int(snippet.get("line"))
        except (TypeError, ValueError):
            continue
        if line > 0:
            return line
    return None


def _merge_rule_read_result(rules: list[dict[str, Any]], read_result: dict[str, Any]) -> list[dict[str, Any]]:
    path = str(read_result.get("path") or "")
    if not path:
        return rules

    merged_rules: list[dict[str, Any]] = []
    found = False
    for rule in rules:
        if str(rule.get("path") or "") == path:
            merged_rules.append(_merge_rule_context(rule, read_result))
            found = True
        else:
            merged_rules.append(rule)

    if not found:
        merged_rules.append(
            _merge_rule_context(
                {"path": path, "score": 0, "snippets": read_result.get("snippets") or []},
                read_result,
            )
        )
    return merged_rules


def _merge_rule_context(rule: dict[str, Any], read_result: dict[str, Any]) -> dict[str, Any]:
    merged = dict(rule)
    read_snippets = read_result.get("snippets")
    if not merged.get("snippets") and isinstance(read_snippets, list):
        merged["snippets"] = read_snippets
    if isinstance(read_snippets, list):
        merged["read_snippets"] = read_snippets
    merged["content"] = str(read_result.get("content") or "")
    merged["read_start_line"] = read_result.get("start_line")
    merged["read_end_line"] = read_result.get("end_line")
    merged["line_count"] = read_result.get("line_count")
    merged["read_truncated"] = bool(read_result.get("truncated"))
    return merged


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
        "business_rule_resolve": server.business_rule_resolve,
        "business_rule_list": server.business_rule_list,
        "business_rule_search": server.business_rule_search,
        "business_rule_read": server.business_rule_read,
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
        "The user message may already include resolved date context, selected table metadata, and selected business rules. "
        "Use business_rule_resolve when you need to re-check whether the question is ambiguous. "
        "If business_rule_resolve says clarification_required, ask the clarification question and do not write SQL. "
        "Use selected table metadata only; do not call pg_schema_overview unless no structured business rules exist. "
        "Treat fixed business-rule logic as mandatory SQL constraints. "
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
    step = TraceStep(
        name=name,
        status=status,  # type: ignore[arg-type]
        summary=summary,
        detail=_json_safe(detail),
    )
    trace.append(step)
    _emit_trace(step)
    _log_agent_debug("agent.trace", step.model_dump(mode="json"))


def _tool_summary(name: str, output: Any) -> str:
    if name == "current_date_context" and isinstance(output, dict):
        return f"Resolved today as {output.get('today')} in {output.get('timezone')}."
    if name == "business_rule_list" and isinstance(output, list):
        return f"Listed {len(output)} business rule file(s)."
    if name == "business_rule_resolve" and isinstance(output, dict):
        if output.get("clarification_required"):
            return (
                "Business rule routing needs clarification "
                f"(confidence {output.get('confidence')}, {output.get('candidate_count', 0)} candidate(s))."
            )
        selected = output.get("selected_tables")
        selected_count = len(selected) if isinstance(selected, list) else 0
        return (
            f"Resolved {selected_count} selected table(s) from business rules "
            f"(confidence {output.get('confidence')})."
        )
    if name == "business_rule_search" and isinstance(output, list):
        return _business_rule_summary(output)
    if name == "business_rule_read" and isinstance(output, dict):
        path = output.get("path")
        start_line = output.get("start_line")
        end_line = output.get("end_line")
        if start_line and end_line:
            return f"Read business rule {path}:L{start_line}-L{end_line}."
        return f"Read business rule {path}."
    if name == "pg_schema_overview" and isinstance(output, dict):
        return f"Loaded {output.get('table_count', 0)} table(s) from PostgreSQL."
    if name == "pg_validate_sql" and isinstance(output, dict):
        return "SQL passed readonly validation." if output.get("ok") else str(output.get("reason"))
    if name == "pg_query" and isinstance(output, dict):
        return f"Readonly query returned {output.get('row_count', 0)} row(s)."
    return "MCP tool call completed."


def _business_rule_summary(rules: list[Any]) -> str:
    if not rules:
        return "Found 0 matching business rule file(s)."

    labels: list[str] = []
    for item in rules[:3]:
        if not isinstance(item, dict):
            continue
        path = str(item.get("path") or "")
        snippets = item.get("snippets")
        line = None
        if isinstance(snippets, list) and snippets and isinstance(snippets[0], dict):
            line = snippets[0].get("line")
        labels.append(f"{path}:L{line}" if path and line else path)

    suffix = "" if len(rules) <= 3 else f", +{len(rules) - 3} more"
    return f"Found {len(rules)} matching business rule file(s): {', '.join(labels)}{suffix}."


def _emit_trace(step: TraceStep) -> None:
    callback = _TRACE_CALLBACK.get()
    if callback is None:
        return
    try:
        callback(step)
    except Exception:
        LOGGER.exception("Agent trace callback failed.")


def _log_agent_debug(label: str, payload: Any) -> None:
    log_path = _agent_debug_log_path()
    if log_path is None:
        return
    record = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "event": label,
        "payload": _json_safe(payload),
    }
    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("a", encoding="utf-8") as file:
            file.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception:
        LOGGER.exception("Failed to write Agent debug log.")


def _agent_debug_log_path() -> Path | None:
    try:
        from backend.app.config import PROJECT_ROOT, get_settings

        settings = get_settings()
        if not settings.agent_verbose_debug:
            return None
        log_path = settings.agent_debug_log_path.expanduser()
        if not log_path.is_absolute():
            log_path = PROJECT_ROOT / log_path
        return log_path.resolve()
    except Exception:
        return None


def _preview(value: Any) -> Any:
    if isinstance(value, dict):
        preview = dict(value)
        if "content" in preview and isinstance(preview["content"], str) and len(preview["content"]) > 1200:
            preview["content"] = preview["content"][:1200] + "...[truncated]"
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
