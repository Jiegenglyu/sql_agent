from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr


StepStatus = Literal["pending", "running", "success", "warning", "error"]
UiLanguage = Literal["auto", "zh", "en"]


class TraceStep(BaseModel):
    name: str
    status: StepStatus
    summary: str
    detail: dict[str, Any] = Field(default_factory=dict)


class AgentQueryRequest(BaseModel):
    question: str = Field(min_length=1, max_length=4000)
    execute: bool = True
    language: UiLanguage = "auto"
    max_rows: int | None = Field(default=None, ge=1, le=1000)


class AgentQueryResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    question: str
    answer: str
    sql: str
    executed: bool
    trace: list[TraceStep]
    rules: list[dict[str, Any]]
    db_schema: dict[str, Any] | None = Field(default=None, alias="schema")
    validation: dict[str, Any]
    result: dict[str, Any] | None = None
    token_usage: "TokenUsage" = Field(default_factory=lambda: TokenUsage())


class RuleSearchResponse(BaseModel):
    query: str
    results: list[dict[str, Any]]


class SqlValidationRequest(BaseModel):
    sql: str = Field(min_length=1, max_length=20000)
    max_rows: int | None = Field(default=None, ge=1, le=5000)


class SqlValidationResponse(BaseModel):
    ok: bool
    reason: str | None = None
    normalized_sql: str | None = None
    limited_sql: str | None = None


class SqlExecuteRequest(BaseModel):
    sql: str = Field(min_length=1, max_length=20000)
    max_rows: int | None = Field(default=None, ge=1, le=5000)


class SqlExecuteResponse(BaseModel):
    columns: list[str]
    rows: list[dict[str, Any]]
    row_count: int
    limited_sql: str


class TableMetadataResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    table_schema: str = Field(alias="schema")
    table: str
    table_type: str | None = None
    estimated_rows: int | None = None
    comment: str | None = None
    columns: list[dict[str, Any]] = Field(default_factory=list)
    indexes: list[dict[str, Any]] = Field(default_factory=list)
    error: str | None = None


class SchemaMetadataResponse(BaseModel):
    tables: list[TableMetadataResponse]
    table_count: int
    failed_count: int = 0
    max_workers: int = 4
    statement_timeout_ms: int = 5000


class HealthResponse(BaseModel):
    status: Literal["ok"]
    database_configured: bool
    llm_configured: bool
    llm_provider: str
    llm_model: str | None = None
    app_timezone: str
    business_rules_dir: str
    token_usage: "TokenUsage" = Field(default_factory=lambda: TokenUsage())


class TokenUsage(BaseModel):
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    requests: int = 0


class DatabaseRuntimeConfig(BaseModel):
    configured: bool
    host: str | None = None
    port: int | None = None
    database: str | None = None
    username: str | None = None
    password_configured: bool = False
    sslmode: str | None = None
    database_url_preview: str | None = None


class LlmRuntimeConfig(BaseModel):
    provider: str
    base_url: str | None = None
    model: str | None = None
    api_key_configured: bool = False
    timeout_seconds: int


class RuntimeConfigResponse(BaseModel):
    app_timezone: str
    pg_max_rows: int
    pg_statement_timeout_ms: int
    pg_schema_limit: int
    database: DatabaseRuntimeConfig
    llm: LlmRuntimeConfig


class ConfigTestResponse(BaseModel):
    ok: bool
    message: str
    latency_ms: int | None = None
    detail: dict[str, Any] = Field(default_factory=dict)


class RuntimeConfigUpdate(BaseModel):
    app_timezone: str | None = Field(default=None, max_length=100)
    pg_max_rows: int | None = Field(default=None, ge=1, le=5000)
    pg_statement_timeout_ms: int | None = Field(default=None, ge=100, le=120000)
    pg_schema_limit: int | None = Field(default=None, ge=1, le=500)

    llm_provider: str | None = Field(default=None, max_length=100)
    llm_base_url: str | None = Field(default=None, max_length=500)
    llm_model: str | None = Field(default=None, max_length=200)
    llm_api_key: SecretStr | None = Field(default=None, max_length=2000)
    llm_timeout_seconds: int | None = Field(default=None, ge=1, le=300)

    database_url: SecretStr | None = Field(default=None, max_length=2000)
    db_host: str | None = Field(default=None, max_length=300)
    db_port: int | None = Field(default=None, ge=1, le=65535)
    db_name: str | None = Field(default=None, max_length=200)
    db_user: str | None = Field(default=None, max_length=200)
    db_password: SecretStr | None = Field(default=None, max_length=1000)
    db_sslmode: str | None = Field(default=None, max_length=50)
