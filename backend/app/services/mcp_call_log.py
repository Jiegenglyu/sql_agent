from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any

from backend.app.config import PROJECT_ROOT


LOG_PATH = PROJECT_ROOT / "logs" / "mcp-calls.jsonl"
MAX_RECORD_BYTES = 500_000


def append_mcp_call(record: dict[str, Any]) -> None:
    payload = {
        "ts": datetime.now(timezone.utc).isoformat(),
        **_json_safe(record),
    }
    text = json.dumps(payload, ensure_ascii=False, default=str)
    if len(text.encode("utf-8")) > MAX_RECORD_BYTES:
        payload = _compact_record(payload)
        text = json.dumps(payload, ensure_ascii=False, default=str)

    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with LOG_PATH.open("a", encoding="utf-8") as file:
        file.write(text + "\n")


def read_mcp_calls(*, limit: int = 100) -> list[dict[str, Any]]:
    if not LOG_PATH.exists():
        return []
    selected: list[str] = []
    with LOG_PATH.open("r", encoding="utf-8", errors="replace") as file:
        for line in file:
            if line.strip():
                selected.append(line)
                if len(selected) > limit:
                    selected.pop(0)

    records: list[dict[str, Any]] = []
    for line in reversed(selected):
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(item, dict):
            records.append(item)
    return records


def _compact_record(record: dict[str, Any]) -> dict[str, Any]:
    compact = dict(record)
    response = compact.get("response")
    if isinstance(response, dict):
        compact["response"] = {
            **response,
            "trace": _compact_list(response.get("trace"), 12),
            "rules": _compact_rules(response.get("rules")),
            "schema": _compact_schema(response.get("schema")),
        }
    return compact


def _compact_list(value: Any, limit: int) -> Any:
    if not isinstance(value, list):
        return value
    return value[:limit]


def _compact_rules(value: Any) -> Any:
    if not isinstance(value, list):
        return value
    rules: list[dict[str, Any]] = []
    for item in value[:8]:
        if not isinstance(item, dict):
            continue
        rule = dict(item)
        content = rule.get("content")
        if isinstance(content, str) and len(content) > 1200:
            rule["content"] = content[:1200] + "...[truncated]"
        rules.append(rule)
    return rules


def _compact_schema(value: Any) -> Any:
    if not isinstance(value, dict):
        return value
    schema = dict(value)
    tables = schema.get("tables")
    if isinstance(tables, list):
        schema["tables"] = tables[:12]
    return schema


def _json_safe(value: Any) -> Any:
    return json.loads(json.dumps(value, default=str, ensure_ascii=False))
