import unittest

from backend.app.services.sql_guard import SqlGuardError, guard_select_sql, validate_select_sql


class SqlGuardTests(unittest.TestCase):
    def test_allows_simple_select(self) -> None:
        guarded = guard_select_sql("SELECT 1 AS ok", max_rows=5)
        self.assertIn("LIMIT 5", guarded.limited_sql)

    def test_allows_semicolon_inside_literal(self) -> None:
        validation = validate_select_sql("SELECT ';' AS value", max_rows=5)
        self.assertTrue(validation["ok"])

    def test_rejects_multiple_statements(self) -> None:
        with self.assertRaises(SqlGuardError):
            guard_select_sql("SELECT 1; SELECT 2", max_rows=5)

    def test_rejects_write_statement(self) -> None:
        with self.assertRaises(SqlGuardError):
            guard_select_sql("DELETE FROM users", max_rows=5)

    def test_rejects_data_modifying_cte(self) -> None:
        with self.assertRaises(SqlGuardError):
            guard_select_sql("WITH x AS (DELETE FROM users RETURNING *) SELECT * FROM x", max_rows=5)

    def test_rejects_dangerous_function(self) -> None:
        with self.assertRaises(SqlGuardError):
            guard_select_sql("SELECT pg_sleep(10)", max_rows=5)


if __name__ == "__main__":
    unittest.main()
