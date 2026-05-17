from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from backend.app.config import get_settings
from backend.app.services.business_rules import BusinessRuleError, list_rule_files, read_rule
from backend.app.services.llm import chat_completion, is_llm_configured


CapabilityLanguage = str

_CACHE: dict[tuple[str, bool, tuple[tuple[str, int, int], ...], tuple[str, str | None, bool]], dict[str, Any]] = {}


def public_capabilities(
    *,
    language: CapabilityLanguage = "zh",
    use_llm: bool = True,
    refresh: bool = False,
) -> dict[str, Any]:
    """Return a public, non-database-facing summary of what the Agent can answer."""
    if refresh:
        _CACHE.clear()

    normalized_language = _normalize_language(language)
    records = _capability_records()
    settings = get_settings()
    cache_key = (
        normalized_language,
        use_llm,
        _rules_signature(),
        (settings.llm_provider, settings.llm_model, bool(settings.llm_api_key)),
    )
    cached = _CACHE.get(cache_key)
    if cached is not None:
        return cached

    fallback_summary = _fallback_summary(records, language=normalized_language)
    generated_by = "fallback"
    llm_error = None
    summary = fallback_summary

    if use_llm and records and is_llm_configured():
        try:
            summary = _llm_summary(records, language=normalized_language)
            generated_by = "llm"
        except Exception as exc:
            llm_error = str(exc)
            summary = fallback_summary

    result = {
        "summary": _redact_internal_names(summary),
        "generated_by": generated_by,
        "llm_error": llm_error,
        "rule_count": len(records),
        "topics": _public_topics(records),
    }
    _CACHE[cache_key] = result
    return result


def public_capability_text(*, language: CapabilityLanguage = "zh", use_llm: bool = True) -> str:
    capabilities = public_capabilities(language=language, use_llm=use_llm)
    return str(capabilities["summary"])


def public_capability_resource() -> str:
    capabilities = public_capabilities(language="zh", use_llm=True)
    return json.dumps(capabilities, ensure_ascii=False, indent=2)


def public_tool_description() -> str:
    summary = public_capability_text(language="zh", use_llm=False)
    return (
        "Ask the SQL Agent a business data question. "
        "The tool returns a public answer only and does not expose SQL, schemas, tables, traces, or raw rows. "
        "Current business capability summary: "
        f"{_truncate(summary, 900)}"
    )


def _capability_records() -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    try:
        files = list_rule_files()
    except BusinessRuleError:
        return []

    for relative_path in files:
        if Path(relative_path).name.lower() == "readme.md":
            continue
        try:
            rule = read_rule(relative_path)
        except (BusinessRuleError, OSError):
            continue
        content = str(rule.get("content") or "")
        if not content.strip():
            continue
        records.append(_parse_capability_record(relative_path, content))
    return records


def _parse_capability_record(relative_path: str, content: str) -> dict[str, Any]:
    lines = content.splitlines()
    title = _first_heading(lines) or Path(relative_path).stem.replace("_", " ")
    aliases = _metadata_values(lines, "aliases")
    sections = _business_sections(lines)
    return {
        "title": title,
        "aliases": aliases,
        "topics": sections,
    }


def _first_heading(lines: list[str]) -> str | None:
    for line in lines:
        match = re.match(r"^#\s+(.+?)\s*$", line)
        if match:
            return _clean_public_text(match.group(1))
    return None


def _metadata_values(lines: list[str], key: str) -> list[str]:
    values: list[str] = []
    pattern = re.compile(rf"^(?:[-*]\s*)?{re.escape(key)}\s*[:：]\s*(.+)$", re.IGNORECASE)
    for line in lines:
        match = pattern.match(line.strip())
        if not match:
            continue
        values.extend(_split_list_value(match.group(1)))
    return _unique_clean(values)


def _business_sections(lines: list[str]) -> list[dict[str, Any]]:
    sections: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    in_business_logic = False

    for line in lines:
        stripped = line.strip()
        if stripped.startswith("###"):
            in_business_logic = "业务逻辑" in stripped or "business" in stripped.lower()
            current = None
            continue
        match = re.match(r"^##\s+(.+?)\s*$", stripped)
        if match and in_business_logic:
            current = {"name": _clean_public_text(match.group(1)), "keywords": [], "notes": []}
            sections.append(current)
            continue
        if current is None:
            continue
        keyword_match = re.match(r"^keywords\s*[:：]\s*(.+)$", stripped, flags=re.IGNORECASE)
        if keyword_match:
            current["keywords"].extend(_split_list_value(keyword_match.group(1)))
            current["keywords"] = _unique_clean(current["keywords"])
            continue
        if stripped.startswith("-"):
            note = _clean_public_text(stripped.lstrip("- ").strip())
            if note:
                current["notes"].append(note)

    return sections


def _fallback_summary(records: list[dict[str, Any]], *, language: str) -> str:
    if not records:
        return (
            "当前没有可用的业务规则摘要。请先在业务规则目录中配置可查询的指标和口径。"
            if language == "zh"
            else "No business capability summary is available yet. Configure business rules first."
        )

    topics = _public_topics(records)
    topic_text = "、".join(topics[:12]) if language == "zh" else ", ".join(topics[:12])
    if len(topics) > 12:
        topic_text += " 等" if language == "zh" else ", and more"

    if language == "en":
        return (
            "This SQL Agent can answer business data questions covered by the current rule set, including "
            f"{topic_text}. It supports natural-language questions about time ranges, latest available data, "
            "and common business dimensions defined by the rules. Ask a concrete metric, object, time range, "
            "or grouping dimension."
        )

    return (
        "这个 SQL Agent 可以回答当前业务规则覆盖的数据问题，包括："
        f"{topic_text}。支持按自然语言询问时间范围、最新可用数据，以及规则中定义的常见业务维度。"
        "提问时最好说明具体指标、对象、时间范围或分组维度。"
    )


def _llm_summary(records: list[dict[str, Any]], *, language: str) -> str:
    language_instruction = (
        "用中文输出。" if language == "zh" else "Write in English."
    )
    message = chat_completion(
        messages=[
            {
                "role": "system",
                "content": (
                    "You summarize the public capabilities of a business data SQL Agent for another AI agent. "
                    "Use only the provided business-rule capability records. "
                    "Do not mention internal table names, schema names, file paths, SQL, database structure, or implementation details. "
                    "Keep it concise and action-oriented."
                ),
            },
            {
                "role": "user",
                "content": "\n".join(
                    [
                        language_instruction,
                        "Summarize what kinds of questions this agent can answer in 4-6 short bullet points.",
                        "Mention useful example question types, but do not invent capabilities.",
                        "",
                        json.dumps(records, ensure_ascii=False),
                    ]
                ),
            },
        ],
    )
    return str(message.get("content") or "").strip()


def _public_topics(records: list[dict[str, Any]]) -> list[str]:
    topics: list[str] = []
    for record in records:
        for section in record.get("topics") or []:
            if isinstance(section, dict):
                topics.append(str(section.get("name") or ""))
        aliases = record.get("aliases")
        if isinstance(aliases, list):
            topics.extend(str(alias) for alias in aliases[:4])
    return _unique_clean(_redact_internal_names(topic) for topic in topics if topic)


def _rules_signature() -> tuple[tuple[str, int, int], ...]:
    settings = get_settings()
    base = settings.business_rules_dir
    if not base.is_absolute():
        from backend.app.config import PROJECT_ROOT

        base = PROJECT_ROOT / base
    signature: list[tuple[str, int, int]] = []
    try:
        files = list_rule_files()
    except BusinessRuleError:
        return tuple()
    for relative_path in files:
        path = (base / relative_path).resolve()
        try:
            stat = path.stat()
        except OSError:
            continue
        signature.append((relative_path, stat.st_mtime_ns, stat.st_size))
    return tuple(signature)


def _split_list_value(value: str) -> list[str]:
    return [item.strip() for item in re.split(r"[,，、]", value) if item.strip()]


def _unique_clean(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        clean = _clean_public_text(value)
        if not clean or clean in seen:
            continue
        result.append(clean)
        seen.add(clean)
    return result


def _clean_public_text(value: str) -> str:
    clean = _redact_internal_names(value.strip())
    clean = re.sub(r"\s+", " ", clean)
    return clean.strip()


def _redact_internal_names(value: str) -> str:
    clean = re.sub(r"`[A-Za-z_][\w]*\.[A-Za-z_][\w]*`", "业务数据", value)
    clean = re.sub(r"\b[A-Za-z_][\w]*\.[A-Za-z_][\w]*\b", "业务数据", clean)
    return clean


def _truncate(value: str, limit: int) -> str:
    if len(value) <= limit:
        return value
    return value[:limit].rstrip() + "..."


def _normalize_language(language: str) -> str:
    clean = (language or "zh").strip().lower()
    return "en" if clean == "en" else "zh"
