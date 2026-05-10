from __future__ import annotations

from dataclasses import dataclass
import re


class SqlGuardError(ValueError):
    """Raised when SQL does not satisfy the read-only policy."""


@dataclass(frozen=True)
class GuardedSQL:
    normalized_sql: str
    limited_sql: str


FORBIDDEN_KEYWORDS = {
    "alter",
    "analyze",
    "call",
    "cluster",
    "comment",
    "copy",
    "create",
    "delete",
    "do",
    "drop",
    "execute",
    "grant",
    "insert",
    "listen",
    "lock",
    "merge",
    "notify",
    "reindex",
    "refresh",
    "revoke",
    "security",
    "truncate",
    "update",
    "vacuum",
}

FORBIDDEN_FUNCTIONS = {
    "dblink",
    "lo_export",
    "lo_import",
    "pg_copy",
    "pg_execute_server_program",
    "pg_ls_dir",
    "pg_read_binary_file",
    "pg_read_file",
    "pg_sleep",
    "pg_stat_file",
}


def guard_select_sql(sql: str, max_rows: int) -> GuardedSQL:
    normalized = _normalize(sql)
    policy_text = _strip_comments_and_literals(normalized)
    first = _first_keyword(policy_text)

    if first not in {"select", "with"}:
        raise SqlGuardError("Only SELECT or read-only WITH queries are allowed.")

    _reject_multiple_statements(normalized)
    _reject_forbidden_terms(policy_text)

    limited_sql = f"SELECT * FROM (\n{normalized}\n) AS agent_limited_result\nLIMIT {int(max_rows)}"
    return GuardedSQL(normalized_sql=normalized, limited_sql=limited_sql)


def validate_select_sql(sql: str, max_rows: int = 200) -> dict[str, str | bool | None]:
    try:
        guarded = guard_select_sql(sql, max_rows=max_rows)
    except SqlGuardError as exc:
        return {
            "ok": False,
            "reason": str(exc),
            "normalized_sql": None,
            "limited_sql": None,
        }
    return {
        "ok": True,
        "reason": None,
        "normalized_sql": guarded.normalized_sql,
        "limited_sql": guarded.limited_sql,
    }


def _normalize(sql: str) -> str:
    value = sql.strip()
    if not value:
        raise SqlGuardError("SQL is empty.")
    if "\x00" in value:
        raise SqlGuardError("SQL contains a NUL byte.")
    if len(value) > 20_000:
        raise SqlGuardError("SQL exceeds the maximum allowed length.")
    if value.endswith(";"):
        value = value[:-1].strip()
    return value


def _first_keyword(sql: str) -> str | None:
    match = re.search(r"[A-Za-z_][A-Za-z0-9_]*", sql)
    return match.group(0).lower() if match else None


def _reject_forbidden_terms(policy_text: str) -> None:
    lowered = policy_text.lower()
    for keyword in FORBIDDEN_KEYWORDS:
        if re.search(rf"\b{re.escape(keyword)}\b", lowered):
            raise SqlGuardError(f"Forbidden SQL keyword: {keyword.upper()}.")
    for function_name in FORBIDDEN_FUNCTIONS:
        if re.search(rf"\b{re.escape(function_name)}\s*\(", lowered):
            raise SqlGuardError(f"Forbidden SQL function: {function_name}.")


def _reject_multiple_statements(sql: str) -> None:
    state = "normal"
    i = 0
    while i < len(sql):
        ch = sql[i]
        nxt = sql[i + 1] if i + 1 < len(sql) else ""

        if state == "normal":
            if ch == "'":
                state = "single"
            elif ch == '"':
                state = "double"
            elif ch == "-" and nxt == "-":
                state = "line_comment"
                i += 1
            elif ch == "/" and nxt == "*":
                state = "block_comment"
                i += 1
            elif ch == ";":
                if sql[i + 1 :].strip():
                    raise SqlGuardError("Multiple SQL statements are not allowed.")
                return
        elif state == "single":
            if ch == "'" and nxt == "'":
                i += 1
            elif ch == "'":
                state = "normal"
        elif state == "double":
            if ch == '"' and nxt == '"':
                i += 1
            elif ch == '"':
                state = "normal"
        elif state == "line_comment":
            if ch in {"\n", "\r"}:
                state = "normal"
        elif state == "block_comment":
            if ch == "*" and nxt == "/":
                state = "normal"
                i += 1
        i += 1


def _strip_comments_and_literals(sql: str) -> str:
    output: list[str] = []
    state = "normal"
    i = 0
    while i < len(sql):
        ch = sql[i]
        nxt = sql[i + 1] if i + 1 < len(sql) else ""

        if state == "normal":
            if ch == "'":
                output.append(" ")
                state = "single"
            elif ch == '"':
                output.append(" ")
                state = "double"
            elif ch == "-" and nxt == "-":
                output.append(" ")
                state = "line_comment"
                i += 1
            elif ch == "/" and nxt == "*":
                output.append(" ")
                state = "block_comment"
                i += 1
            else:
                output.append(ch)
        elif state == "single":
            output.append(" ")
            if ch == "'" and nxt == "'":
                i += 1
                output.append(" ")
            elif ch == "'":
                state = "normal"
        elif state == "double":
            output.append(" ")
            if ch == '"' and nxt == '"':
                i += 1
                output.append(" ")
            elif ch == '"':
                state = "normal"
        elif state == "line_comment":
            output.append(" ")
            if ch in {"\n", "\r"}:
                state = "normal"
        elif state == "block_comment":
            output.append(" ")
            if ch == "*" and nxt == "/":
                i += 1
                output.append(" ")
                state = "normal"
        i += 1
    return "".join(output)
