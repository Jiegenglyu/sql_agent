export type StepStatus = "pending" | "running" | "success" | "warning" | "error";

export interface TraceStep {
  name: string;
  status: StepStatus;
  summary: string;
  detail: Record<string, unknown>;
}

export interface RuleSearchResult {
  path: string;
  score: number;
  snippets: Array<{
    line: number;
    text: string;
  }>;
  read_snippets?: Array<{
    line: number;
    text: string;
  }>;
  content?: string;
  read_start_line?: number | null;
  read_end_line?: number | null;
  line_count?: number | null;
  read_truncated?: boolean;
}

export interface SqlValidation {
  ok: boolean;
  reason: string | null;
  normalized_sql: string | null;
  limited_sql: string | null;
}

export interface QueryResult {
  columns: string[];
  rows: Array<Record<string, unknown>>;
  row_count: number;
  limited_sql: string | null;
  sql?: string;
  source_tables?: string[];
}

export interface TableMetadata {
  schema: string;
  table: string;
  table_type: string | null;
  estimated_rows: number | null;
  comment: string | null;
  columns: Array<Record<string, unknown>>;
  indexes: Array<Record<string, unknown>>;
  error: string | null;
}

export interface SchemaMetadataResponse {
  tables: TableMetadata[];
  table_count: number;
  failed_count: number;
  max_workers: number;
  statement_timeout_ms: number;
  schemas: string[];
}

export interface AgentResponse {
  question: string;
  answer: string;
  sql: string;
  executed: boolean;
  trace: TraceStep[];
  rules: RuleSearchResult[];
  schema: Record<string, unknown> | null;
  validation: SqlValidation;
  result: QueryResult | null;
  token_usage: TokenUsage;
  status: "success" | "error";
  error: AgentError | null;
}

export interface AgentError {
  code: string;
  message: string;
}

export interface PublicMcpResponse {
  question: string | null;
  caller?: string | null;
  answer: string;
  status: "success" | "error";
  executed: boolean;
  needs_clarification: boolean;
  row_count: number | null;
  result: QueryResult | null;
  error: AgentError | null;
  trace: TraceStep[];
  rules: RuleSearchResult[];
  schema: Record<string, unknown> | null;
  token_usage: TokenUsage;
  capabilities?: Record<string, unknown>;
}

export interface McpCallRecord {
  ts: string;
  tool: string;
  caller: string;
  question: string | null;
  status: "success" | "error";
  row_count: number | null;
  error: AgentError | null;
  source_tables: string[];
  response: PublicMcpResponse | Record<string, unknown>;
}

export interface McpCallsResponse {
  calls: McpCallRecord[];
  count: number;
}

export interface HealthResponse {
  status: "ok";
  database_configured: boolean;
  llm_configured: boolean;
  llm_provider: string;
  llm_model: string | null;
  app_timezone: string;
  business_rules_dir: string;
  agent_verbose_debug: boolean;
  mcp_auth_configured: boolean;
  mcp_key_count: number;
  token_usage: TokenUsage;
}

export interface TokenUsage {
  prompt_tokens: number;
  completion_tokens: number;
  total_tokens: number;
  requests: number;
}

export interface DatabaseRuntimeConfig {
  configured: boolean;
  host: string | null;
  port: number | null;
  database: string | null;
  username: string | null;
  password_configured: boolean;
  sslmode: string | null;
  database_url_preview: string | null;
}

export interface LlmRuntimeConfig {
  provider: string;
  base_url: string | null;
  model: string | null;
  api_key_configured: boolean;
  timeout_seconds: number;
}

export interface RuntimeConfigResponse {
  app_timezone: string;
  pg_max_rows: number;
  pg_statement_timeout_ms: number;
  pg_schema_limit: number;
  pg_schemas: string[];
  agent_verbose_debug: boolean;
  mcp_auth_configured: boolean;
  mcp_key_count: number;
  database: DatabaseRuntimeConfig;
  llm: LlmRuntimeConfig;
}

export interface ConfigTestResponse {
  ok: boolean;
  message: string;
  latency_ms: number | null;
  detail: Record<string, unknown>;
}

export interface RuntimeConfigUpdate {
  app_timezone?: string;
  pg_max_rows?: number;
  pg_statement_timeout_ms?: number;
  pg_schema_limit?: number;
  pg_schemas?: string[];
  agent_verbose_debug?: boolean;
  llm_provider?: string;
  llm_base_url?: string;
  llm_model?: string;
  llm_api_key?: string;
  llm_timeout_seconds?: number;
  db_host?: string;
  db_port?: number;
  db_name?: string;
  db_user?: string;
  db_password?: string;
  db_sslmode?: string;
}

export type UiLanguage = "zh" | "en";
