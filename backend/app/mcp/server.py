from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from backend.app.config import get_settings
from backend.app.services.business_rules import list_rule_files, read_rule, search_rules
from backend.app.services.postgres import describe_table, execute_select, list_schemas, list_tables, schema_overview
from backend.app.services.sql_guard import validate_select_sql


try:
    from fastmcp import FastMCP
except ImportError:  # pragma: no cover - compatibility with the official MCP SDK
    from mcp.server.fastmcp import FastMCP


mcp = FastMCP("sql-agent-tools")


@mcp.tool()
def current_date_context(timezone_name: str | None = None) -> dict[str, Any]:
    """Return current date and week boundaries for resolving relative date questions."""
    settings = get_settings()
    requested_timezone = timezone_name or settings.app_timezone
    try:
        tz = ZoneInfo(requested_timezone)
    except ZoneInfoNotFoundError:
        requested_timezone = "UTC"
        tz = ZoneInfo("UTC")

    now = datetime.now(tz)
    today = now.date()
    week_start = today - timedelta(days=today.weekday())
    week_end = week_start + timedelta(days=6)
    return {
        "timezone": requested_timezone,
        "now": now.isoformat(timespec="seconds"),
        "today": today.isoformat(),
        "week_start": week_start.isoformat(),
        "week_end": week_end.isoformat(),
    }


@mcp.tool()
def pg_list_schemas() -> list[str]:
    """List non-system PostgreSQL schemas."""
    return list_schemas()


@mcp.tool()
def pg_list_tables(schema: str | None = None, limit: int = 80) -> list[dict[str, Any]]:
    """List PostgreSQL tables visible to the configured read-only role and schema scope."""
    return list_tables(schema=schema, limit=limit)


@mcp.tool()
def pg_describe_table(schema: str, table: str) -> dict[str, Any]:
    """Describe columns, indexes, and comments for a PostgreSQL table."""
    return describe_table(schema=schema, table=table)


@mcp.tool()
def pg_schema_overview(limit: int = 80) -> dict[str, Any]:
    """Return a compact schema overview for SQL generation within the configured schema scope."""
    return schema_overview(limit=limit)


@mcp.tool()
def pg_validate_sql(sql: str, max_rows: int = 200) -> dict[str, Any]:
    """Validate that SQL is a single read-only SELECT or WITH statement."""
    return validate_select_sql(sql, max_rows=max_rows)


@mcp.tool()
def pg_query(sql: str, max_rows: int = 200) -> dict[str, Any]:
    """Execute a guarded read-only PostgreSQL SELECT query."""
    return execute_select(sql, max_rows=max_rows)


@mcp.tool()
def business_rule_search(query: str, limit: int = 8) -> list[dict[str, Any]]:
    """Search only within the configured business rules directory."""
    return search_rules(query, limit=limit)


@mcp.tool()
def business_rule_read(path: str) -> dict[str, Any]:
    """Read a single business rule file by relative path."""
    return read_rule(path)


@mcp.tool()
def business_rule_list() -> list[str]:
    """List business rule files under the configured directory."""
    return list_rule_files()


if __name__ == "__main__":
    mcp.run()
