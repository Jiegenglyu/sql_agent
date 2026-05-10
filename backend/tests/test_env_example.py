import unittest
from pathlib import Path

from backend.app.config import PROJECT_ROOT, Settings


class EnvExampleTests(unittest.TestCase):
    def test_env_example_documents_config_keys(self) -> None:
        env_example = PROJECT_ROOT / ".env.example"
        keys = _env_keys(env_example)
        settings_keys = {
            field.alias
            for field in Settings.model_fields.values()
            if isinstance(field.alias, str) and field.alias.isupper()
        }
        project_keys = {
            "BACKEND_HOST",
            "BACKEND_PORT",
            "FRONTEND_HOST",
            "FRONTEND_PORT",
            "POSTGRES_DB",
            "POSTGRES_HOST_PORT",
            "POSTGRES_PASSWORD",
            "POSTGRES_READONLY_PASSWORD",
            "POSTGRES_READONLY_USER",
            "POSTGRES_USER",
            "UV_CACHE_DIR",
            "VITE_API_BASE_URL",
            "VITE_API_PREFIX",
        }

        missing = (settings_keys | project_keys) - keys

        self.assertEqual(set(), missing)


def _env_keys(path: Path) -> set[str]:
    keys: set[str] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, _ = stripped.split("=", 1)
        keys.add(key.strip())
    return keys


if __name__ == "__main__":
    unittest.main()
