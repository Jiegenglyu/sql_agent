from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

from backend.app.services.sql_guard import guard_select_sql


class DatabaseError(RuntimeError):
    """Raised when PostgreSQL access fails."""


METADATA_MAX_WORKERS = 4
METADATA_STATEMENT_TIMEOUT_MS = 5000
PREVIEW_MAX_ROWS = 100


def execute_select(
    sql: str,
    *,
    max_rows: int | None = None,
    statement_timeout_ms: int | None = None,
) -> dict[str, Any]:
    settings = _settings()
    rows_limit = min(max_rows or settings.pg_max_rows, 5000)
    guarded = guard_select_sql(sql, max_rows=rows_limit)

    with _connect() as conn:
        _configure_session(conn, statement_timeout_ms=statement_timeout_ms)
        with conn.transaction():
            conn.execute("SET TRANSACTION READ ONLY")
            with conn.cursor() as cur:
                cur.execute(guarded.limited_sql)
                columns = [column.name for column in (cur.description or [])]
                rows = cur.fetchall()

    return {
        "columns": columns,
        "rows": rows,
        "row_count": len(rows),
        "limited_sql": guarded.limited_sql,
    }


def preview_table(schema: str, table: str, *, max_rows: int = 10) -> dict[str, Any]:
    rows_limit = min(max(max_rows, 1), PREVIEW_MAX_ROWS)
    sql = f"SELECT * FROM {_quote_identifier(schema)}.{_quote_identifier(table)}"
    return execute_select(sql, max_rows=rows_limit, statement_timeout_ms=_metadata_timeout_ms())


def list_schemas() -> list[str]:
    query = """
        SELECT schema_name
        FROM information_schema.schemata
        WHERE schema_name <> 'information_schema'
          AND schema_name NOT LIKE 'pg_%'
        ORDER BY schema_name
    """
    with _connect() as conn:
        _configure_session(conn)
        with conn.cursor() as cur:
            cur.execute(query)
            return [row["schema_name"] for row in cur.fetchall()]


def list_tables(
    schema: str | None = None,
    *,
    limit: int | None = None,
    statement_timeout_ms: int | None = None,
) -> list[dict[str, Any]]:
    settings = _settings()
    table_limit = max(1, min(limit or settings.pg_schema_limit, 500))
    params: list[Any] = []
    where = [
        "t.table_schema <> 'information_schema'",
        "t.table_schema NOT LIKE 'pg_%%'",
    ]
    if schema:
        where.append("t.table_schema = %s")
        params.append(schema)

    query = f"""
        SELECT
            t.table_schema,
            t.table_name,
            t.table_type,
            CASE
                WHEN c.reltuples IS NULL OR c.reltuples < 0 THEN NULL
                ELSE c.reltuples::bigint
            END AS estimated_rows
        FROM information_schema.tables t
        LEFT JOIN pg_namespace n ON n.nspname = t.table_schema
        LEFT JOIN pg_class c ON c.relnamespace = n.oid AND c.relname = t.table_name
        WHERE {' AND '.join(where)}
        ORDER BY t.table_schema, t.table_name
        LIMIT %s
    """
    params.append(table_limit)

    with _connect() as conn:
        _configure_session(conn, statement_timeout_ms=statement_timeout_ms)
        with conn.cursor() as cur:
            cur.execute(query, params)
            return list(cur.fetchall())


def describe_table(
    schema: str,
    table: str,
    *,
    statement_timeout_ms: int | None = None,
) -> dict[str, Any]:
    metadata_query = """
        SELECT
            t.table_type,
            CASE
                WHEN c.reltuples IS NULL OR c.reltuples < 0 THEN NULL
                ELSE c.reltuples::bigint
            END AS estimated_rows
        FROM information_schema.tables t
        LEFT JOIN pg_namespace n ON n.nspname = t.table_schema
        LEFT JOIN pg_class c ON c.relnamespace = n.oid AND c.relname = t.table_name
        WHERE t.table_schema = %s
          AND t.table_name = %s
        LIMIT 1
    """
    columns_query = """
        SELECT
            column_name,
            data_type,
            is_nullable,
            column_default,
            ordinal_position
        FROM information_schema.columns
        WHERE table_schema = %s
          AND table_name = %s
        ORDER BY ordinal_position
    """
    indexes_query = """
        SELECT indexname, indexdef
        FROM pg_indexes
        WHERE schemaname = %s
          AND tablename = %s
        ORDER BY indexname
    """
    comment_query = """
        SELECT obj_description(c.oid) AS table_comment
        FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = %s
          AND c.relname = %s
        LIMIT 1
    """

    with _connect() as conn:
        _configure_session(conn, statement_timeout_ms=statement_timeout_ms)
        with conn.cursor() as cur:
            cur.execute(metadata_query, [schema, table])
            metadata_row = cur.fetchone()
            cur.execute(columns_query, [schema, table])
            columns = list(cur.fetchall())
            cur.execute(indexes_query, [schema, table])
            indexes = list(cur.fetchall())
            cur.execute(comment_query, [schema, table])
            comment_row = cur.fetchone()

    return {
        "schema": schema,
        "table": table,
        "table_type": metadata_row["table_type"] if metadata_row else None,
        "estimated_rows": metadata_row["estimated_rows"] if metadata_row else None,
        "comment": comment_row["table_comment"] if comment_row else None,
        "columns": columns,
        "indexes": indexes,
        "error": None,
    }


def schema_overview(*, limit: int | None = None) -> dict[str, Any]:
    return collect_schema_metadata(limit=limit)


def collect_schema_metadata(*, limit: int | None = None) -> dict[str, Any]:
    statement_timeout_ms = _metadata_timeout_ms()
    tables = list_tables(limit=limit, statement_timeout_ms=statement_timeout_ms)
    if not tables:
        return {
            "tables": [],
            "table_count": 0,
            "failed_count": 0,
            "max_workers": METADATA_MAX_WORKERS,
            "statement_timeout_ms": statement_timeout_ms,
        }

    described: list[dict[str, Any] | None] = [None] * len(tables)
    workers = min(METADATA_MAX_WORKERS, len(tables))
    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="pg-metadata") as executor:
        futures = {
            executor.submit(_describe_table_for_collection, item, statement_timeout_ms): index
            for index, item in enumerate(tables)
        }
        for future in as_completed(futures):
            index = futures[future]
            item = tables[index]
            try:
                described[index] = future.result()
            except Exception as exc:  # pragma: no cover - worker catches expected table failures
                described[index] = _failed_table_metadata(item, str(exc))

    result_tables = [item for item in described if item is not None]
    return {
        "tables": result_tables,
        "table_count": len(result_tables),
        "failed_count": sum(1 for item in result_tables if item.get("error")),
        "max_workers": METADATA_MAX_WORKERS,
        "statement_timeout_ms": statement_timeout_ms,
    }


def _describe_table_for_collection(item: dict[str, Any], statement_timeout_ms: int) -> dict[str, Any]:
    try:
        metadata = describe_table(
            item["table_schema"],
            item["table_name"],
            statement_timeout_ms=statement_timeout_ms,
        )
    except Exception as exc:
        return _failed_table_metadata(item, str(exc))

    if metadata.get("table_type") is None:
        metadata["table_type"] = item.get("table_type")
    if metadata.get("estimated_rows") is None:
        metadata["estimated_rows"] = item.get("estimated_rows")
    return metadata


def _failed_table_metadata(item: dict[str, Any], error: str) -> dict[str, Any]:
    return {
        "schema": item.get("table_schema"),
        "table": item.get("table_name"),
        "table_type": item.get("table_type"),
        "estimated_rows": item.get("estimated_rows"),
        "comment": None,
        "columns": [],
        "indexes": [],
        "error": error,
    }


def _settings():
    from backend.app.config import get_settings

    return get_settings()


def _connect():
    settings = _settings()
    if not settings.database_url:
        raise DatabaseError("DATABASE_URL is not configured.")
    try:
        import psycopg
        from psycopg.rows import dict_row
    except ImportError as exc:
        raise DatabaseError("Install backend dependencies before using PostgreSQL.") from exc
    return psycopg.connect(settings.database_url, autocommit=True, row_factory=dict_row)


def _configure_session(conn: Any, *, statement_timeout_ms: int | None = None) -> None:
    timeout_ms = int(statement_timeout_ms or _settings().pg_statement_timeout_ms)
    conn.execute(f"SET statement_timeout = {timeout_ms}")


def _metadata_timeout_ms() -> int:
    return min(int(_settings().pg_statement_timeout_ms), METADATA_STATEMENT_TIMEOUT_MS)


def _quote_identifier(value: str) -> str:
    if not value or "\x00" in value:
        raise ValueError("Invalid PostgreSQL identifier.")
    return '"' + value.replace('"', '""') + '"'
