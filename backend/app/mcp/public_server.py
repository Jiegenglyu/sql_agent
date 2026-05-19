from __future__ import annotations

import argparse
import os
from typing import Any, Literal, cast

from backend.app.config import get_settings
from backend.app.models import AgentQueryRequest, AgentQueryResponse, UiLanguage
from backend.app.services.business_capabilities import (
    public_capabilities,
    public_capability_resource,
    public_tool_description,
)
from backend.app.services.agent import run_agent_query
from backend.app.services.mcp_call_log import append_mcp_call


try:
    from fastmcp import FastMCP
except ImportError:  # pragma: no cover - compatibility with the official MCP SDK
    from mcp.server.fastmcp import FastMCP


Transport = Literal["stdio", "http", "sse", "streamable-http"]

mcp = FastMCP("sql-agent")


@mcp.resource(
    "capabilities://sql-agent",
    name="sql-agent-capabilities",
    description="Public summary of the business questions this SQL Agent can answer.",
    mime_type="application/json",
)
def capabilities_resource() -> str:
    """Return the current public capability summary as a resource."""
    return public_capability_resource()


@mcp.tool(description="Describe what business questions the SQL Agent can answer based on current rules.")
def describe_capabilities(
    api_key: str,
    language: str = "zh",
    refresh: bool = False,
    caller: str = "unknown",
) -> dict[str, Any]:
    """Return a public capability summary generated from the current business rules."""
    auth_error = _auth_error(api_key, caller=caller)
    if auth_error:
        _record_call(tool="describe_capabilities", caller=caller, question=None, response=auth_error)
        return auth_error
    result = public_capabilities(language=language, use_llm=True, refresh=refresh)
    _record_call(
        tool="describe_capabilities",
        caller=caller,
        question=None,
        response={
            "status": "success",
            "answer": result.get("summary"),
            "executed": False,
            "error": None,
            "capabilities": result,
        },
    )
    return result


@mcp.tool(description=public_tool_description())
def ask_agent(
    question: str,
    api_key: str,
    caller: str = "unknown",
    language: str = "auto",
    max_rows: int | None = None,
    include_capabilities: bool = False,
) -> dict[str, Any]:
    """Ask the SQL Agent a business question and return only the public answer surface."""
    auth_error = _auth_error(api_key, question=question, caller=caller)
    if auth_error:
        _record_call(tool="ask_agent", caller=caller, question=question, response=auth_error)
        return auth_error
    if _is_capability_question(question):
        capability_result = _capability_answer(question=question, language=language, caller=caller)
        _record_call(tool="ask_agent", caller=caller, question=question, response=capability_result)
        return capability_result

    request = AgentQueryRequest(
        question=question,
        execute=True,
        language=_normalize_language(language),
        max_rows=max_rows,
    )
    response = run_agent_query(request)
    result = _public_response(response)
    result["caller"] = caller
    if include_capabilities:
        result["capabilities"] = public_capabilities(language=_public_language(language), use_llm=True)
    _record_call(tool="ask_agent", caller=caller, question=question, response=result)
    return result


def _normalize_language(language: str) -> UiLanguage:
    clean = (language or "auto").strip().lower()
    if clean in {"auto", "zh", "en"}:
        return cast(UiLanguage, clean)
    raise ValueError("language must be one of: auto, zh, en")


def _public_language(language: str) -> str:
    clean = (language or "zh").strip().lower()
    return "en" if clean == "en" else "zh"


def _is_capability_question(question: str) -> bool:
    text = question.strip().lower()
    return any(
        term in text
        for term in [
            "能查什么",
            "可以查什么",
            "支持查询",
            "有哪些能力",
            "what can you answer",
            "what can this agent answer",
            "capabilities",
        ]
    )


def _capability_answer(*, question: str, language: str, caller: str) -> dict[str, Any]:
    capabilities = public_capabilities(language=_public_language(language), use_llm=True)
    return {
        "question": question,
        "caller": caller,
        "status": "success",
        "answer": str(capabilities.get("summary") or ""),
        "executed": False,
        "needs_clarification": False,
        "row_count": None,
        "result": None,
        "error": None,
        "trace": [],
        "rules": [],
        "schema": None,
        "token_usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0, "requests": 0},
        "capabilities": capabilities,
    }


def _public_response(response: AgentQueryResponse) -> dict[str, Any]:
    result = _public_result(response)
    error = _public_error(response)
    return {
        "question": response.question,
        "answer": _public_answer(response),
        "status": response.status,
        "executed": response.executed,
        "needs_clarification": _needs_clarification(response),
        "row_count": _row_count(response),
        "result": result,
        "error": error,
        "trace": [step.model_dump(mode="json") for step in response.trace],
        "rules": response.rules,
        "schema": response.db_schema,
        "token_usage": _token_usage(response),
    }


def _public_answer(response: AgentQueryResponse) -> str:
    return response.answer


def _public_result(response: AgentQueryResponse) -> dict[str, Any] | None:
    if not isinstance(response.result, dict):
        if response.sql:
            return {
                "columns": [],
                "rows": [],
                "row_count": 0,
                "sql": response.sql,
                "limited_sql": None,
                "source_tables": _source_tables(response),
            }
        return None

    return {
        "columns": response.result.get("columns") if isinstance(response.result.get("columns"), list) else [],
        "rows": response.result.get("rows") if isinstance(response.result.get("rows"), list) else [],
        "row_count": _row_count(response) or 0,
        "sql": response.sql,
        "limited_sql": response.result.get("limited_sql"),
        "source_tables": _source_tables(response),
    }


def _public_error(response: AgentQueryResponse) -> dict[str, Any] | None:
    if isinstance(response.error, dict):
        return response.error
    if response.status != "error":
        return None
    for step in reversed(response.trace):
        if step.status == "error":
            return {"code": step.name, "message": step.summary}
    return {"code": "agent_error", "message": response.answer}


def _source_tables(response: AgentQueryResponse) -> list[str]:
    tables: list[str] = []
    seen: set[str] = set()
    seen_bare: set[str] = set()

    schema_tables = response.db_schema.get("tables") if isinstance(response.db_schema, dict) else None
    if isinstance(schema_tables, list):
        for item in schema_tables:
            if not isinstance(item, dict):
                continue
            table = _format_table_name(item.get("schema"), item.get("table"))
            bare = str(item.get("table") or "").strip()
            if table and table not in seen:
                tables.append(table)
                seen.add(table)
                if bare:
                    seen_bare.add(bare)

    for rule in response.rules:
        if not isinstance(rule, dict):
            continue
        bare = str(rule.get("table") or "").strip()
        table = _format_table_name(rule.get("schema"), rule.get("table"))
        if table and table not in seen and bare not in seen_bare:
            tables.append(table)
            seen.add(table)
            if bare:
                seen_bare.add(bare)

    return tables


def _format_table_name(schema: Any, table: Any) -> str | None:
    clean_table = str(table or "").strip()
    if not clean_table:
        return None
    clean_schema = str(schema or "").strip()
    return f"{clean_schema}.{clean_table}" if clean_schema else clean_table


def _needs_clarification(response: AgentQueryResponse) -> bool:
    return any(step.name == "clarification" for step in response.trace)


def _row_count(response: AgentQueryResponse) -> int | None:
    if not isinstance(response.result, dict):
        return None
    row_count = response.result.get("row_count")
    return row_count if isinstance(row_count, int) else None


def _token_usage(response: AgentQueryResponse) -> dict[str, int]:
    usage = response.token_usage
    if isinstance(usage, dict):
        return {
            "prompt_tokens": _int_value(usage.get("prompt_tokens")),
            "completion_tokens": _int_value(usage.get("completion_tokens")),
            "total_tokens": _int_value(usage.get("total_tokens")),
            "requests": _int_value(usage.get("requests")),
        }
    return usage.model_dump(mode="json")


def _int_value(value: Any) -> int:
    if isinstance(value, bool):
        return 0
    if isinstance(value, int):
        return max(value, 0)
    if isinstance(value, float):
        return max(int(value), 0)
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return 0


def _auth_error(
    api_key: str | None,
    *,
    question: str | None = None,
    caller: str | None = None,
) -> dict[str, Any] | None:
    settings = get_settings()
    keys = set(settings.mcp_api_keys)
    if not keys:
        return {
            "question": question,
            "caller": caller,
            "status": "error",
            "answer": "MCP_API_KEYS 未配置，拒绝执行 MCP 调用。",
            "executed": False,
            "needs_clarification": False,
            "row_count": None,
            "result": None,
            "error": {
                "code": "auth_not_configured",
                "message": "MCP_API_KEYS is required for this deployment.",
            },
            "trace": [],
            "rules": [],
            "schema": None,
            "token_usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0, "requests": 0},
        }
    if (api_key or "").strip() in keys:
        return None
    return {
        "question": question,
        "caller": caller,
        "status": "error",
        "answer": "MCP API Key 无效，拒绝执行 MCP 调用。",
        "executed": False,
        "needs_clarification": False,
        "row_count": None,
        "result": None,
        "error": {"code": "auth_failed", "message": "Invalid MCP API key."},
        "trace": [],
        "rules": [],
        "schema": None,
        "token_usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0, "requests": 0},
    }


def _record_call(*, tool: str, caller: str | None, question: str | None, response: dict[str, Any]) -> None:
    try:
        append_mcp_call(
            {
                "tool": tool,
                "caller": caller or "unknown",
                "question": question,
                "status": response.get("status"),
                "row_count": response.get("row_count"),
                "error": response.get("error"),
                "source_tables": ((response.get("result") or {}).get("source_tables") if isinstance(response.get("result"), dict) else []),
                "response": response,
            }
        )
    except Exception:
        return


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Run the northbound SQL Agent MCP server.")
    parser.add_argument(
        "--transport",
        choices=["stdio", "http", "sse", "streamable-http"],
        default=os.environ.get("PUBLIC_MCP_TRANSPORT", "streamable-http"),
    )
    parser.add_argument("--host", default=os.environ.get("PUBLIC_MCP_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("PUBLIC_MCP_PORT", "8001")))
    parser.add_argument("--path", default=os.environ.get("PUBLIC_MCP_PATH", "/mcp"))
    parser.add_argument(
        "--stateful-http",
        action="store_true",
        default=not _env_bool("PUBLIC_MCP_STATELESS_HTTP", default=False),
        help="Keep HTTP MCP sessions on the server. This is the default remote MCP mode.",
    )
    parser.add_argument(
        "--stateless-http",
        action="store_true",
        default=False,
        help="Run HTTP MCP in stateless mode for clients that do not need a server-side session.",
    )
    args = parser.parse_args(argv)

    transport = cast(Transport, args.transport)
    if transport == "stdio":
        mcp.run(transport=transport)
    elif transport in {"http", "streamable-http"}:
        stateless_http = bool(args.stateless_http or not args.stateful_http)
        mcp.run(
            transport=transport,
            host=args.host,
            port=args.port,
            path=args.path,
            stateless_http=stateless_http,
        )
    else:
        mcp.run(transport=transport, host=args.host, port=args.port, path=args.path)


def _env_bool(name: str, *, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


if __name__ == "__main__":
    main()
