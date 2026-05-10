from __future__ import annotations

from typing import Any

from backend.app.services.sql_guard import guard_select_sql


class DatabaseError(RuntimeError):
    """Raised when PostgreSQL access fails."""


def execute_select(sql: str, *, max_rows: int | None = None) -> dict[str, Any]:
    settings = _settings()
    rows_limit = min(max_rows or settings.pg_max_rows, 5000)
    guarded = guard_select_sql(sql, max_rows=rows_limit)

    with _connect() as conn:
        _configure_session(conn)
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


def list_tables(schema: str | None = None, *, limit: int | None = None) -> list[dict[str, Any]]:
    settings = _settings()
    table_limit = min(limit or settings.pg_schema_limit, 500)
    params: list[Any] = []
    where = [
        "table_schema <> 'information_schema'",
        "table_schema NOT LIKE 'pg_%%'",
    ]
    if schema:
        where.append("table_schema = %s")
        params.append(schema)

    query = f"""
        SELECT table_schema, table_name, table_type
        FROM information_schema.tables
        WHERE {' AND '.join(where)}
        ORDER BY table_schema, table_name
        LIMIT %s
    """
    params.append(table_limit)

    with _connect() as conn:
        _configure_session(conn)
        with conn.cursor() as cur:
            cur.execute(query, params)
            return list(cur.fetchall())


def describe_table(schema: str, table: str) -> dict[str, Any]:
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
        _configure_session(conn)
        with conn.cursor() as cur:
            cur.execute(columns_query, [schema, table])
            columns = list(cur.fetchall())
            cur.execute(indexes_query, [schema, table])
            indexes = list(cur.fetchall())
            cur.execute(comment_query, [schema, table])
            comment_row = cur.fetchone()

    return {
        "schema": schema,
        "table": table,
        "comment": comment_row["table_comment"] if comment_row else None,
        "columns": columns,
        "indexes": indexes,
    }


def schema_overview(*, limit: int | None = None) -> dict[str, Any]:
    tables = list_tables(limit=limit)
    described: list[dict[str, Any]] = []
    for item in tables:
        described.append(describe_table(item["table_schema"], item["table_name"]))
    return {
        "tables": described,
        "table_count": len(described),
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


def _configure_session(conn: Any) -> None:
    timeout_ms = int(_settings().pg_statement_timeout_ms)
    conn.execute(f"SET statement_timeout = {timeout_ms}")
