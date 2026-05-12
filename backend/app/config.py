from functools import lru_cache
from pathlib import Path
import re
from typing import Annotated

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


PROJECT_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = Field(default="sql-agent", alias="APP_NAME")
    api_prefix: str = Field(default="/api", alias="APP_API_PREFIX")
    app_timezone: str = Field(default="Asia/Shanghai", alias="APP_TIMEZONE")
    cors_origins: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["http://localhost:5173", "http://127.0.0.1:5173"],
        alias="CORS_ORIGINS",
    )

    database_url: str | None = Field(default=None, alias="DATABASE_URL")
    pg_max_rows: int = Field(default=200, alias="PG_MAX_ROWS")
    pg_statement_timeout_ms: int = Field(default=5000, alias="PG_STATEMENT_TIMEOUT_MS")
    pg_schema_limit: int = Field(default=80, alias="PG_SCHEMA_LIMIT")
    pg_schemas: Annotated[list[str], NoDecode] = Field(default_factory=list, alias="PG_SCHEMAS")

    business_rules_dir: Path = Field(
        default=Path("backend/business_rules"),
        alias="BUSINESS_RULES_DIR",
    )
    business_rule_max_file_bytes: int = Field(
        default=256_000,
        alias="BUSINESS_RULE_MAX_FILE_BYTES",
    )
    business_rule_max_results: int = Field(default=8, alias="BUSINESS_RULE_MAX_RESULTS")

    llm_provider: str = Field(default="manual", alias="LLM_PROVIDER")
    llm_base_url: str | None = Field(default=None, alias="LLM_BASE_URL")
    llm_api_key: str | None = Field(default=None, alias="LLM_API_KEY")
    llm_model: str | None = Field(default=None, alias="LLM_MODEL")
    llm_timeout_seconds: int = Field(default=45, alias="LLM_TIMEOUT_SECONDS")

    @field_validator("cors_origins", mode="before")
    @classmethod
    def split_cors_origins(cls, value: object) -> object:
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value

    @field_validator("pg_schemas", mode="before")
    @classmethod
    def split_pg_schemas(cls, value: object) -> object:
        if isinstance(value, str):
            return _unique_clean_names(value)
        if isinstance(value, list):
            return _unique_clean_names(value)
        return value

    @field_validator("api_prefix")
    @classmethod
    def normalize_api_prefix(cls, value: str) -> str:
        clean = value.strip().rstrip("/")
        if not clean:
            return ""
        if not clean.startswith("/"):
            return "/" + clean
        return clean

    @field_validator(
        "pg_max_rows",
        "pg_statement_timeout_ms",
        "pg_schema_limit",
        "business_rule_max_file_bytes",
        "business_rule_max_results",
    )
    @classmethod
    def positive_int(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("value must be positive")
        return value


def _env_file_signature() -> tuple[int | None, int | None]:
    env_path = PROJECT_ROOT / ".env"
    try:
        stat = env_path.stat()
    except FileNotFoundError:
        return (None, None)
    return (stat.st_mtime_ns, stat.st_size)


@lru_cache
def _get_settings(env_file_signature: tuple[int | None, int | None]) -> Settings:
    return Settings()


def get_settings() -> Settings:
    return _get_settings(_env_file_signature())


def reload_settings() -> Settings:
    _get_settings.cache_clear()
    return get_settings()


def _unique_clean_names(value: str | list[object]) -> list[str]:
    raw_items: list[object]
    if isinstance(value, str):
        raw_items = re.split(r"[\s,]+", value)
    else:
        raw_items = value

    names: list[str] = []
    seen: set[str] = set()
    for raw_item in raw_items:
        for item in re.split(r"[\s,]+", str(raw_item)):
            clean = item.strip()
            if not clean or clean in seen:
                continue
            names.append(clean)
            seen.add(clean)
    return names
