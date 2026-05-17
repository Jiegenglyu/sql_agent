from __future__ import annotations

import argparse
import os
import re
from typing import Any, Literal, cast

from backend.app.models import AgentQueryRequest, AgentQueryResponse, UiLanguage
from backend.app.services.business_capabilities import (
    public_capabilities,
    public_capability_resource,
    public_tool_description,
)
from backend.app.services.agent import run_agent_query


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
def describe_capabilities(language: str = "zh", refresh: bool = False) -> dict[str, Any]:
    """Return a public capability summary generated from the current business rules."""
    return public_capabilities(language=language, use_llm=True, refresh=refresh)


@mcp.tool(description=public_tool_description())
def ask_agent(
    question: str,
    language: str = "auto",
    max_rows: int | None = None,
    include_capabilities: bool = False,
) -> dict[str, Any]:
    """Ask the SQL Agent a business question and return only the public answer surface."""
    if _is_capability_question(question):
        return _capability_answer(question=question, language=language)

    request = AgentQueryRequest(
        question=question,
        execute=True,
        language=_normalize_language(language),
        max_rows=max_rows,
    )
    response = run_agent_query(request)
    result = _public_response(response)
    if include_capabilities:
        result["capabilities"] = public_capabilities(language=_public_language(language), use_llm=True)
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


def _capability_answer(*, question: str, language: str) -> dict[str, Any]:
    capabilities = public_capabilities(language=_public_language(language), use_llm=True)
    return {
        "question": question,
        "answer": str(capabilities.get("summary") or ""),
        "executed": False,
        "needs_clarification": False,
        "row_count": None,
        "token_usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0, "requests": 0},
        "capabilities": capabilities,
    }


def _public_response(response: AgentQueryResponse) -> dict[str, Any]:
    return {
        "question": response.question,
        "answer": _public_answer(response),
        "executed": response.executed,
        "needs_clarification": _needs_clarification(response),
        "row_count": _row_count(response),
        "token_usage": _token_usage(response),
    }


def _public_answer(response: AgentQueryResponse) -> str:
    return _redact_internal_table_names(response.answer)


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


def _redact_internal_table_names(answer: str) -> str:
    cleaned_lines: list[str] = []
    for line in answer.splitlines():
        clean_line = re.sub(r"^(\s*\d+\.\s*[^:：]+)\s*[:：]\s*\S+\s*$", r"\1", line)
        clean_line = re.sub(r"`[A-Za-z_][\w]*\.[A-Za-z_][\w]*`", "业务数据", clean_line)
        clean_line = re.sub(r"\b[A-Za-z_][\w]*\.[A-Za-z_][\w]*\b", "业务数据", clean_line)
        cleaned_lines.append(clean_line)
    return "\n".join(cleaned_lines)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Run the northbound SQL Agent MCP server.")
    parser.add_argument(
        "--transport",
        choices=["stdio", "http", "sse", "streamable-http"],
        default=os.environ.get("PUBLIC_MCP_TRANSPORT", "stdio"),
    )
    parser.add_argument("--host", default=os.environ.get("PUBLIC_MCP_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("PUBLIC_MCP_PORT", "8001")))
    parser.add_argument("--path", default=os.environ.get("PUBLIC_MCP_PATH", "/mcp"))
    parser.add_argument(
        "--stateful-http",
        action="store_true",
        default=not _env_bool("PUBLIC_MCP_STATELESS_HTTP", default=True),
        help="Keep HTTP MCP sessions on the server. By default public HTTP MCP runs stateless.",
    )
    args = parser.parse_args(argv)

    transport = cast(Transport, args.transport)
    if transport == "stdio":
        mcp.run(transport=transport)
    elif transport in {"http", "streamable-http"}:
        mcp.run(
            transport=transport,
            host=args.host,
            port=args.port,
            path=args.path,
            stateless_http=not args.stateful_http,
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
