from __future__ import annotations

from pathlib import Path
from time import perf_counter
from typing import Any
from urllib.parse import parse_qs, quote, unquote, urlencode, urlsplit, urlunsplit

from pydantic import SecretStr

from backend.app.config import PROJECT_ROOT, get_settings, reload_settings
from backend.app.models import RuntimeConfigUpdate
from backend.app.services.token_usage import record_token_usage


ENV_PATH = PROJECT_ROOT / ".env"


class RuntimeConfigError(ValueError):
    """Raised when a runtime configuration update is invalid."""


def read_runtime_config() -> dict[str, Any]:
    settings = get_settings()
    parsed_database = parse_database_url(settings.database_url)
    return {
        "app_timezone": settings.app_timezone,
        "pg_max_rows": settings.pg_max_rows,
        "pg_statement_timeout_ms": settings.pg_statement_timeout_ms,
        "pg_schema_limit": settings.pg_schema_limit,
        "database": parsed_database,
        "llm": {
            "provider": settings.llm_provider,
            "base_url": settings.llm_base_url,
            "model": settings.llm_model,
            "api_key_configured": bool(settings.llm_api_key),
            "timeout_seconds": settings.llm_timeout_seconds,
        },
    }


def update_runtime_config(update: RuntimeConfigUpdate) -> dict[str, Any]:
    env_values = _read_env_values(ENV_PATH)
    current_settings = get_settings()
    current_database = parse_database_url(current_settings.database_url)
    values: dict[str, str | None] = {}

    _set_optional(values, "APP_TIMEZONE", update.app_timezone)
    _set_optional(values, "PG_MAX_ROWS", update.pg_max_rows)
    _set_optional(values, "PG_STATEMENT_TIMEOUT_MS", update.pg_statement_timeout_ms)
    _set_optional(values, "PG_SCHEMA_LIMIT", update.pg_schema_limit)
    _set_optional(values, "LLM_PROVIDER", update.llm_provider)
    _set_optional(values, "LLM_BASE_URL", update.llm_base_url)
    _set_optional(values, "LLM_MODEL", update.llm_model)
    _set_optional(values, "LLM_TIMEOUT_SECONDS", update.llm_timeout_seconds)

    llm_api_key = _secret_value(update.llm_api_key)
    if llm_api_key is not None:
        values["LLM_API_KEY"] = llm_api_key

    database_url = _database_url_from_update(update, current_database, env_values)
    if database_url is not None:
        values["DATABASE_URL"] = database_url

    if values:
        _write_env_values(ENV_PATH, values)
        reload_settings()

    return read_runtime_config()


def test_database_config(update: RuntimeConfigUpdate) -> dict[str, Any]:
    database_url = _database_url_for_test(update)
    statement_timeout_ms = update.pg_statement_timeout_ms or get_settings().pg_statement_timeout_ms

    try:
        import psycopg
        from psycopg.rows import dict_row
    except ImportError as exc:
        raise RuntimeConfigError("后端缺少 psycopg，无法测试 PostgreSQL 连接。") from exc

    started = perf_counter()
    try:
        with psycopg.connect(database_url, autocommit=True, row_factory=dict_row, connect_timeout=5) as conn:
            conn.execute(f"SET statement_timeout = {int(statement_timeout_ms)}")
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT
                        current_database() AS database,
                        current_user AS username,
                        inet_server_addr()::text AS server_addr,
                        inet_server_port() AS server_port
                    """
                )
                row = cur.fetchone() or {}
    except Exception as exc:
        raise RuntimeConfigError(f"PostgreSQL 连接失败：{exc}") from exc

    return {
        "ok": True,
        "message": "PostgreSQL 连接成功。",
        "latency_ms": _elapsed_ms(started),
        "detail": dict(row),
    }


def test_llm_config(update: RuntimeConfigUpdate) -> dict[str, Any]:
    llm = _llm_config_for_test(update)

    try:
        import httpx
    except ImportError as exc:
        raise RuntimeConfigError("后端缺少 httpx，无法测试大模型连接。") from exc

    payload = {
        "model": llm["model"],
        "messages": [
            {"role": "system", "content": "Reply with OK only."},
            {"role": "user", "content": "ping"},
        ],
        "temperature": 0,
        "max_tokens": 8,
    }
    headers = {"Authorization": f"Bearer {llm['api_key']}"}
    url = str(llm["base_url"]).rstrip("/") + "/chat/completions"

    started = perf_counter()
    try:
        with httpx.Client(timeout=int(llm["timeout_seconds"])) as client:
            response = client.post(url, json=payload, headers=headers)
            response.raise_for_status()
            data = response.json()
    except Exception as exc:
        raise RuntimeConfigError(f"大模型连接失败：{_http_error_message(exc)}") from exc

    usage = data.get("usage") if isinstance(data, dict) else None
    record_token_usage(usage)
    choice = ((data.get("choices") or [{}])[0] or {}) if isinstance(data, dict) else {}
    message = choice.get("message") if isinstance(choice, dict) else {}
    content = str((message or {}).get("content") or "").strip()

    return {
        "ok": True,
        "message": "大模型连接成功。",
        "latency_ms": _elapsed_ms(started),
        "detail": {
            "provider": llm["provider"],
            "model": llm["model"],
            "reply": content[:120],
            "usage": usage or {},
        },
    }


def parse_database_url(database_url: str | None) -> dict[str, Any]:
    if not database_url:
        return {
            "configured": False,
            "host": None,
            "port": None,
            "database": None,
            "username": None,
            "password_configured": False,
            "sslmode": None,
            "database_url_preview": None,
        }

    parsed = urlsplit(database_url)
    database = unquote(parsed.path.lstrip("/")) if parsed.path else None
    query = parse_qs(parsed.query)
    sslmode = query.get("sslmode", [None])[0]
    password = parsed.password

    return {
        "configured": True,
        "host": parsed.hostname,
        "port": parsed.port,
        "database": database,
        "username": unquote(parsed.username or "") or None,
        "password_configured": bool(password),
        "sslmode": sslmode,
        "database_url_preview": _mask_database_url(parsed, database, sslmode),
    }


def _database_url_for_test(update: RuntimeConfigUpdate) -> str:
    env_values = _read_env_values(ENV_PATH)
    settings = get_settings()
    current_database = parse_database_url(settings.database_url)
    database_url = _database_url_from_update(update, current_database, env_values)
    if database_url is None:
        database_url = settings.database_url
    if not database_url:
        raise RuntimeConfigError("请先填写 PostgreSQL 数据库配置。")
    return database_url


def _llm_config_for_test(update: RuntimeConfigUpdate) -> dict[str, Any]:
    settings = get_settings()
    provider = _plain_value(update.llm_provider) or settings.llm_provider
    base_url = _plain_value(update.llm_base_url) or settings.llm_base_url
    model = _plain_value(update.llm_model) or settings.llm_model
    api_key = _secret_value(update.llm_api_key) or settings.llm_api_key
    timeout_seconds = update.llm_timeout_seconds or settings.llm_timeout_seconds

    if provider.lower() in {"", "manual", "none"}:
        raise RuntimeConfigError("LLM_PROVIDER 不能是 manual/none，请填写 OpenAI-compatible Provider。")
    if not base_url or not model or not api_key:
        raise RuntimeConfigError("请填写 LLM Base URL、模型名和 API Key。")

    return {
        "provider": provider,
        "base_url": base_url,
        "model": model,
        "api_key": api_key,
        "timeout_seconds": timeout_seconds,
    }


def _database_url_from_update(
    update: RuntimeConfigUpdate,
    current_database: dict[str, Any],
    env_values: dict[str, str],
) -> str | None:
    direct_database_url = _plain_value(update.database_url)
    if direct_database_url is not None:
        return direct_database_url

    fields = [
        update.db_host,
        update.db_port,
        update.db_name,
        update.db_user,
        update.db_password,
        update.db_sslmode,
    ]
    if all(value is None for value in fields):
        return None

    current_password = _password_from_database_url(env_values.get("DATABASE_URL"))
    host = _plain_value(update.db_host) or current_database.get("host")
    port = update.db_port if update.db_port is not None else current_database.get("port")
    database = _plain_value(update.db_name) or current_database.get("database")
    username = _plain_value(update.db_user) or current_database.get("username")
    password = _secret_value(update.db_password)
    if password is None:
        password = current_password
    sslmode = _plain_value(update.db_sslmode)
    if sslmode is None:
        sslmode = current_database.get("sslmode")

    if not host or not database or not username:
        raise RuntimeConfigError("数据库 host、库名和用户账号不能为空。")

    return build_database_url(
        host=str(host),
        port=int(port) if port else None,
        database=str(database),
        username=str(username),
        password=password,
        sslmode=str(sslmode) if sslmode else None,
    )


def build_database_url(
    *,
    host: str,
    port: int | None,
    database: str,
    username: str,
    password: str | None,
    sslmode: str | None,
) -> str:
    if port is not None and (port <= 0 or port > 65535):
        raise RuntimeConfigError("数据库端口必须在 1 到 65535 之间。")

    auth = quote(username, safe="")
    if password:
        auth += ":" + quote(password, safe="")

    netloc = f"{auth}@{host}"
    if port:
        netloc += f":{port}"

    query = urlencode({"sslmode": sslmode}) if sslmode else ""
    return urlunsplit(("postgresql", netloc, "/" + quote(database, safe=""), query, ""))


def _read_env_values(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values

    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in line:
            continue
        key, raw_value = line.split("=", 1)
        values[key.strip()] = _unquote_env_value(raw_value.strip())
    return values


def _write_env_values(path: Path, updates: dict[str, str | None]) -> None:
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    remaining = dict(updates)
    rewritten: list[str] = []

    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in line:
            rewritten.append(line)
            continue

        key, _ = line.split("=", 1)
        clean_key = key.strip()
        if clean_key in remaining:
            value = remaining.pop(clean_key)
            if value is None:
                rewritten.append(f"{clean_key}=")
            else:
                rewritten.append(f"{clean_key}={_format_env_value(value)}")
        else:
            rewritten.append(line)

    if remaining and rewritten and rewritten[-1].strip():
        rewritten.append("")
    for key, value in remaining.items():
        rewritten.append(f"{key}={_format_env_value(value or '')}")

    path.write_text("\n".join(rewritten) + "\n", encoding="utf-8")


def _set_optional(values: dict[str, str | None], key: str, value: object) -> None:
    plain = _plain_value(value)
    if plain is not None:
        values[key] = plain


def _plain_value(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, SecretStr):
        text = value.get_secret_value().strip()
    else:
        text = str(value).strip()
    return text or None


def _secret_value(value: SecretStr | None) -> str | None:
    if value is None:
        return None
    text = value.get_secret_value().strip()
    return text or None


def _password_from_database_url(database_url: str | None) -> str | None:
    if not database_url:
        return None
    return urlsplit(database_url).password


def _mask_database_url(parsed: Any, database: str | None, sslmode: str | None) -> str:
    username = unquote(parsed.username or "")
    auth = quote(username, safe="") if username else ""
    if parsed.password is not None:
        auth += ":***"
    host = parsed.hostname or ""
    netloc = f"{auth}@{host}" if auth else host
    if parsed.port:
        netloc += f":{parsed.port}"
    query = urlencode({"sslmode": sslmode}) if sslmode else ""
    return urlunsplit((parsed.scheme or "postgresql", netloc, "/" + quote(database or "", safe=""), query, ""))


def _format_env_value(value: str) -> str:
    if not value:
        return ""
    if any(char.isspace() for char in value) or "#" in value or '"' in value:
        escaped = value.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'
    return value


def _unquote_env_value(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        inner = value[1:-1]
        if value[0] == '"':
            return inner.replace('\\"', '"').replace("\\\\", "\\")
        return inner
    return value


def _elapsed_ms(started: float) -> int:
    return max(0, int((perf_counter() - started) * 1000))


def _http_error_message(exc: Exception) -> str:
    response = getattr(exc, "response", None)
    if response is not None:
        try:
            detail = response.json()
        except Exception:
            detail = getattr(response, "text", "")
        status_code = getattr(response, "status_code", "")
        return f"HTTP {status_code}: {detail}"
    return str(exc)
