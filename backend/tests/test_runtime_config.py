import unittest
from urllib.parse import urlsplit

from pydantic import SecretStr

from backend.app.models import RuntimeConfigUpdate
from backend.app.services.runtime_config import (
    _database_url_from_update,
    _plain_value,
    _secret_value,
    build_database_url,
    parse_database_url,
)


class RuntimeConfigTests(unittest.TestCase):
    def test_blank_values_are_treated_as_absent(self) -> None:
        self.assertIsNone(_plain_value(""))
        self.assertIsNone(_plain_value("   "))
        self.assertIsNone(_secret_value(SecretStr("")))
        self.assertIsNone(_secret_value(SecretStr("   ")))

    def test_blank_database_password_preserves_env_password(self) -> None:
        current_url = build_database_url(
            host="localhost",
            port=55432,
            database="circle_demo",
            username="sql_agent_readonly",
            password="env-password",
            sslmode=None,
        )
        current_database = parse_database_url(current_url)
        update = RuntimeConfigUpdate(db_host="127.0.0.1", db_password=SecretStr(""))

        next_url = _database_url_from_update(update, current_database, {"DATABASE_URL": current_url})

        self.assertIsNotNone(next_url)
        parsed = parse_database_url(next_url)
        self.assertEqual(parsed["host"], "127.0.0.1")
        self.assertEqual(urlsplit(next_url).password, "env-password")
        self.assertTrue(parsed["password_configured"])
        self.assertIn(":***@", parsed["database_url_preview"] or "")


if __name__ == "__main__":
    unittest.main()
