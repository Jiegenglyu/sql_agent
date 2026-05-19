from __future__ import annotations

from typing import Any

from backend.app.services.token_usage import record_token_usage


class LLMNotConfigured(RuntimeError):
    """Raised when no SQL generation model is configured."""


def is_llm_configured() -> bool:
    settings = _settings()
    if settings.llm_provider.lower() in {"", "manual", "none"}:
        return False
    return bool(settings.llm_base_url and settings.llm_api_key and settings.llm_model)


def chat_completion(
    *,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None = None,
    tool_choice: str | dict[str, Any] | None = None,
) -> dict[str, Any]:
    settings = _settings()
    if settings.llm_provider.lower() in {"", "manual", "none"}:
        raise LLMNotConfigured("LLM_PROVIDER is manual; set an OpenAI-compatible provider to enable Agent mode.")
    if not settings.llm_base_url or not settings.llm_api_key or not settings.llm_model:
        raise LLMNotConfigured("LLM_BASE_URL, LLM_API_KEY, and LLM_MODEL are required.")

    try:
        import httpx
    except ImportError as exc:
        raise LLMNotConfigured("Install httpx before using LLM generation.") from exc

    payload: dict[str, Any] = {
        "model": settings.llm_model,
        "messages": messages,
        "temperature": 0,
    }
    if tools:
        payload["tools"] = tools
        payload["tool_choice"] = tool_choice or "auto"

    url = settings.llm_base_url.rstrip("/") + "/chat/completions"
    headers = {"Authorization": f"Bearer {settings.llm_api_key}"}
    with httpx.Client(timeout=settings.llm_timeout_seconds) as client:
        response = client.post(url, json=payload, headers=headers)
        response.raise_for_status()
        data = response.json()
    record_token_usage(data.get("usage"))
    return dict(data["choices"][0]["message"])


def generate_sql(
    *,
    question: str,
    schema: dict[str, Any] | None,
    rules: list[dict[str, Any]],
    date_context: dict[str, Any] | None = None,
) -> str | None:
    settings = _settings()
    if settings.llm_provider.lower() in {"", "manual", "none"}:
        return None
    if not settings.llm_base_url or not settings.llm_api_key or not settings.llm_model:
        raise LLMNotConfigured("LLM_BASE_URL, LLM_API_KEY, and LLM_MODEL are required.")

    prompt = _build_prompt(question=question, schema=schema, rules=rules, date_context=date_context)
    message = chat_completion(
        messages=[
            {
                "role": "system",
                "content": (
                    "You generate PostgreSQL SELECT queries only. "
                    "Return one SQL statement and no markdown. "
                    "Use the business rule documents as the source of truth for business logic, joins, filters, "
                    "and metric definitions. Use only tables and columns present in the provided schema. "
                    "Resolve relative dates with the provided date context. "
                    "If the question cannot be answered with the provided rules and schema, return a SELECT "
                    "that produces zero rows with clear column aliases instead of inventing tables or columns."
                ),
            },
            {"role": "user", "content": prompt},
        ],
    )
    return str(message.get("content") or "").strip()


def generate_answer(
    *,
    question: str,
    language: str,
    date_context: dict[str, Any],
    sql: str,
    result: dict[str, Any] | None,
    rules: list[dict[str, Any]],
) -> str | None:
    if not is_llm_configured():
        return None

    language_instruction = {
        "zh": "Answer in Chinese.",
        "en": "Answer in English.",
    }.get(language, "Answer in the same language as the user question.")

    message = chat_completion(
        messages=[
            {
                "role": "system",
                "content": (
                    "You are a business data analyst. Summarize readonly PostgreSQL query results. "
                    "Do not invent numbers. If the result has no rows, say that clearly. "
                    "The UI will render the table separately, so keep the answer concise."
                ),
            },
            {
                "role": "user",
                "content": "\n".join(
                    [
                        language_instruction,
                        "",
                        "User question:",
                        question,
                        "",
                        "Date context:",
                        _compact(date_context, limit=1200),
                        "",
                        "SQL executed:",
                        sql,
                        "",
                        "Query result:",
                        _compact(result or {}, limit=8000),
                        "",
                        "Relevant rules:",
                        _compact(rules, limit=2400),
                    ]
                ),
            },
        ],
    )
    content = str(message.get("content") or "").strip()
    return content or None


def _build_prompt(
    *,
    question: str,
    schema: dict[str, Any] | None,
    rules: list[dict[str, Any]],
    date_context: dict[str, Any] | None = None,
) -> str:
    return "\n".join(
        [
            "User question:",
            question,
            "",
            "Current date context:",
            _compact(date_context or {}, limit=1200),
            "",
            "Relevant business rules:",
            _compact(rules, limit=4000),
            "",
            "Available PostgreSQL schema:",
            _compact(schema or {}, limit=8000),
            "",
            "Constraints:",
            "- Use PostgreSQL syntax.",
            "- Use only tables and columns visible in the provided schema metadata.",
            "- Treat the business rule documents as source-of-truth context for SQL generation.",
            "- Follow join keys and fixed business-rule logic from the Markdown files.",
            "- Generate a single read-only SELECT or WITH query.",
            "- Include a LIMIT when the request does not imply aggregation.",
            "- Do not invent tables, columns, joins, metrics, or values.",
        ]
    )


def _compact(value: Any, *, limit: int) -> str:
    text = repr(value)
    if len(text) <= limit:
        return text
    return text[:limit] + "...[truncated]"


def _settings():
    from backend.app.config import get_settings

    return get_settings()
