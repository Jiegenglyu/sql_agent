from backend.app.mcp.server import (
    current_date_context,
    mcp,
    pg_describe_table,
    pg_list_schemas,
    pg_list_tables,
    pg_query,
    pg_schema_overview,
    pg_validate_sql,
)


__all__ = [
    "mcp",
    "current_date_context",
    "pg_describe_table",
    "pg_list_schemas",
    "pg_list_tables",
    "pg_query",
    "pg_schema_overview",
    "pg_validate_sql",
]


if __name__ == "__main__":
    mcp.run()
