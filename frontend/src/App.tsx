import { FormEvent, KeyboardEvent, PointerEvent as ReactPointerEvent, useEffect, useMemo, useRef, useState } from "react";
import {
  AlertTriangle,
  Bot,
  CheckCircle2,
  Clock3,
  Columns3,
  Database,
  GripVertical,
  KeyRound,
  Languages,
  Loader2,
  RefreshCw,
  Save,
  Search,
  Send,
  Settings,
  ShieldCheck,
  Sparkles,
  Table2,
  TerminalSquare,
  X
} from "lucide-react";

import {
  getHealth,
  getRuntimeConfig,
  getSchemaMetadata,
  previewTable,
  queryAgent,
  testDatabaseConfig,
  testLlmConfig,
  updateRuntimeConfig
} from "./api";
import type {
  AgentResponse,
  ConfigTestResponse,
  HealthResponse,
  QueryResult,
  RuntimeConfigResponse,
  RuntimeConfigUpdate,
  SchemaMetadataResponse,
  TableMetadata,
  TokenUsage,
  TraceStep,
  UiLanguage
} from "./types";

interface CopyText {
  title: string;
  subtitle: string;
  placeholder: string;
  send: string;
  sending: string;
  settings: string;
  openSettings: string;
  closeSettings: string;
  settingsDatabase: string;
  settingsModel: string;
  settingsRuntime: string;
  testConnection: string;
  testModel: string;
  testing: string;
  save: string;
  saving: string;
  saved: string;
  connection: string;
  model: string;
  tokenUsage: string;
  currentQuery: string;
  session: string;
  serverTotal: string;
  prompt: string;
  completion: string;
  total: string;
  requests: string;
  provider: string;
  baseUrl: string;
  modelName: string;
  apiKey: string;
  host: string;
  port: string;
  dbName: string;
  dbUser: string;
  dbPassword: string;
  sslmode: string;
  timezone: string;
  maxRows: string;
  statementTimeout: string;
  schemaLimit: string;
  secretPlaceholder: string;
  dbReady: string;
  dbMissing: string;
  llmReady: string;
  llmMissing: string;
  readonly: string;
  runContext: string;
  answerDetails: string;
  resultTable: string;
  auditSql: string;
  agentTrace: string;
  businessRules: string;
  schema: string;
  examples: string[];
  emptyChat: string;
  rows: string;
  noRows: string;
  emptySql: string;
  emptyTrace: string;
  emptyRules: string;
  emptySchema: string;
  dataExplorer: string;
  collectMetadata: string;
  collectingMetadata: string;
  metadataReady: string;
  metadataEmpty: string;
  metadataFailed: string;
  tableSearch: string;
  tablePreview: string;
  previewRows: string;
  previewLoading: string;
  columns: string;
  indexes: string;
  estimatedRows: string;
  tableType: string;
  failedTables: string;
  noTableSelected: string;
  metadataSafety: string;
}

const COPY = {
  zh: {
    title: "业务数据 Agent",
    subtitle: "用自然语言查询 PostgreSQL，Agent 负责查表、生成只读 SQL 和汇总业务结果。",
    placeholder: "输入业务问题，Shift + Enter 换行",
    send: "发送",
    sending: "查询中",
    settings: "设置",
    openSettings: "打开设置",
    closeSettings: "关闭设置",
    settingsDatabase: "数据库",
    settingsModel: "大模型",
    settingsRuntime: "运行",
    testConnection: "测试连接",
    testModel: "测试模型",
    testing: "测试中",
    save: "保存设置",
    saving: "保存中",
    saved: "已保存",
    connection: "PostgreSQL",
    model: "大模型",
    tokenUsage: "Token 使用量",
    currentQuery: "本次",
    session: "当前会话",
    serverTotal: "服务累计",
    prompt: "输入",
    completion: "输出",
    total: "总量",
    requests: "请求",
    provider: "Provider",
    baseUrl: "Base URL",
    modelName: "模型",
    apiKey: "API Key",
    host: "IP / Host",
    port: "端口",
    dbName: "库名",
    dbUser: "用户账号",
    dbPassword: "密码",
    sslmode: "SSL Mode",
    timezone: "时区",
    maxRows: "最大返回行数",
    statementTimeout: "SQL 超时(ms)",
    schemaLimit: "Schema 表数量",
    secretPlaceholder: "留空保持不变",
    dbReady: "PG 已配置",
    dbMissing: "PG 未配置",
    llmReady: "LLM 已配置",
    llmMissing: "LLM 待配置",
    readonly: "只读查询",
    runContext: "运行上下文",
    answerDetails: "查询明细",
    resultTable: "结果表格",
    auditSql: "审计 SQL",
    agentTrace: "Agent 过程",
    businessRules: "业务规则",
    schema: "数据表",
    examples: ["今天的卡时使用率多少？", "这一周的卡时使用率多少？", "现在 AI infra 总卡数是多少？", "哪些集群有容量压力？"],
    emptyChat: "可以直接开始提问。",
    rows: "行",
    noRows: "暂无结果",
    emptySql: "还没有生成 SQL。",
    emptyTrace: "还没有运行轨迹。",
    emptyRules: "暂无命中的规则。",
    emptySchema: "暂无 schema 信息。",
    dataExplorer: "数据表预览",
    collectMetadata: "收集表元数据",
    collectingMetadata: "收集中",
    metadataReady: "已收集",
    metadataEmpty: "点击收集表元数据后选择表格预览。",
    metadataFailed: "元数据收集失败",
    tableSearch: "搜索 schema 或表名",
    tablePreview: "表格预览",
    previewRows: "预览前 10 行",
    previewLoading: "读取预览中",
    columns: "字段",
    indexes: "索引",
    estimatedRows: "估算行数",
    tableType: "类型",
    failedTables: "失败表",
    noTableSelected: "请选择一张表。",
    metadataSafety: "4 并发 / 5 秒超时 / 估算行数"
  },
  en: {
    title: "Business Data Agent",
    subtitle: "Ask PostgreSQL in natural language. The Agent queries tables, writes readonly SQL, and summarizes results.",
    placeholder: "Ask a business question. Shift + Enter for a new line",
    send: "Send",
    sending: "Querying",
    settings: "Settings",
    openSettings: "Open Settings",
    closeSettings: "Close Settings",
    settingsDatabase: "Database",
    settingsModel: "Model",
    settingsRuntime: "Runtime",
    testConnection: "Test Connection",
    testModel: "Test Model",
    testing: "Testing",
    save: "Save Settings",
    saving: "Saving",
    saved: "Saved",
    connection: "PostgreSQL",
    model: "Model",
    tokenUsage: "Token Usage",
    currentQuery: "Last query",
    session: "Session",
    serverTotal: "Server total",
    prompt: "Prompt",
    completion: "Completion",
    total: "Total",
    requests: "Requests",
    provider: "Provider",
    baseUrl: "Base URL",
    modelName: "Model",
    apiKey: "API Key",
    host: "IP / Host",
    port: "Port",
    dbName: "Database",
    dbUser: "User",
    dbPassword: "Password",
    sslmode: "SSL Mode",
    timezone: "Timezone",
    maxRows: "Max Rows",
    statementTimeout: "SQL Timeout(ms)",
    schemaLimit: "Schema Tables",
    secretPlaceholder: "Leave blank to keep current",
    dbReady: "PG configured",
    dbMissing: "PG missing",
    llmReady: "LLM configured",
    llmMissing: "LLM missing",
    readonly: "Readonly",
    runContext: "Run Context",
    answerDetails: "Details",
    resultTable: "Result Table",
    auditSql: "Audit SQL",
    agentTrace: "Agent Trace",
    businessRules: "Business Rules",
    schema: "Tables",
    examples: [
      "What is today's card-hour utilization?",
      "What is card-hour utilization this week?",
      "How many GPUs does AI infra have now?",
      "Which clusters have capacity pressure?"
    ],
    emptyChat: "Start with a question.",
    rows: "rows",
    noRows: "No result yet",
    emptySql: "No SQL generated yet.",
    emptyTrace: "No trace yet.",
    emptyRules: "No matching rules yet.",
    emptySchema: "No schema loaded yet.",
    dataExplorer: "Table Preview",
    collectMetadata: "Collect Metadata",
    collectingMetadata: "Collecting",
    metadataReady: "Collected",
    metadataEmpty: "Collect table metadata, then select a table to preview.",
    metadataFailed: "Metadata collection failed",
    tableSearch: "Search schema or table",
    tablePreview: "Table Preview",
    previewRows: "Preview first 10 rows",
    previewLoading: "Loading preview",
    columns: "Columns",
    indexes: "Indexes",
    estimatedRows: "Estimated rows",
    tableType: "Type",
    failedTables: "Failed tables",
    noTableSelected: "Select a table.",
    metadataSafety: "4 workers / 5s timeout / estimated rows"
  }
} satisfies Record<UiLanguage, CopyText>;

interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  agent?: AgentResponse;
  error?: boolean;
}

interface ConfigForm {
  app_timezone: string;
  pg_max_rows: string;
  pg_statement_timeout_ms: string;
  pg_schema_limit: string;
  llm_provider: string;
  llm_base_url: string;
  llm_model: string;
  llm_api_key: string;
  llm_timeout_seconds: string;
  db_host: string;
  db_port: string;
  db_name: string;
  db_user: string;
  db_password: string;
  db_sslmode: string;
}

type ConfigTestTarget = "database" | "model";

const EMPTY_USAGE: TokenUsage = {
  prompt_tokens: 0,
  completion_tokens: 0,
  total_tokens: 0,
  requests: 0
};

const PANE_MIN_SIZES: [number, number] = [34, 34];

function App() {
  const [language, setLanguage] = useState<UiLanguage>("zh");
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [runtimeConfig, setRuntimeConfig] = useState<RuntimeConfigResponse | null>(null);
  const [configForm, setConfigForm] = useState<ConfigForm>(() => emptyConfigForm());
  const [draft, setDraft] = useState("这一周的卡时使用率多少？");
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [savingConfig, setSavingConfig] = useState(false);
  const [saveState, setSaveState] = useState<"idle" | "saved">("idle");
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [settingsTab, setSettingsTab] = useState<"database" | "model" | "runtime">("database");
  const [testingConfig, setTestingConfig] = useState<ConfigTestTarget | null>(null);
  const [configTestResult, setConfigTestResult] = useState<Partial<Record<ConfigTestTarget, ConfigTestResponse>>>({});
  const [paneSizes, setPaneSizes] = useState<[number, number]>([48, 52]);
  const [metadata, setMetadata] = useState<SchemaMetadataResponse | null>(null);
  const [metadataLoading, setMetadataLoading] = useState(false);
  const [metadataError, setMetadataError] = useState<string | null>(null);
  const [tableFilter, setTableFilter] = useState("");
  const [selectedTableId, setSelectedTableId] = useState<string | null>(null);
  const [preview, setPreview] = useState<QueryResult | null>(null);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [previewError, setPreviewError] = useState<string | null>(null);
  const messagesRef = useRef<HTMLDivElement>(null);
  const workspaceRef = useRef<HTMLElement>(null);
  const text = COPY[language];

  useEffect(() => {
    refreshStatus().catch((err: Error) => setError(err.message));
  }, []);

  useEffect(() => {
    messagesRef.current?.scrollTo({ top: messagesRef.current.scrollHeight, behavior: "smooth" });
  }, [messages, busy]);

  useEffect(() => {
    if (!settingsOpen) {
      return;
    }

    function handleKeyDown(event: globalThis.KeyboardEvent) {
      if (event.key === "Escape") {
        setSettingsOpen(false);
      }
    }

    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [settingsOpen]);

  const selectedTable = useMemo(() => {
    if (!metadata || !selectedTableId) {
      return null;
    }
    return metadata.tables.find((item) => tableKey(item) === selectedTableId) ?? null;
  }, [metadata, selectedTableId]);

  useEffect(() => {
    if (!selectedTable) {
      setPreview(null);
      setPreviewError(null);
      setPreviewLoading(false);
      return;
    }
    if (selectedTable.error) {
      setPreview(null);
      setPreviewError(selectedTable.error);
      setPreviewLoading(false);
      return;
    }

    let ignore = false;
    setPreviewLoading(true);
    setPreviewError(null);
    previewTable(selectedTable.schema, selectedTable.table, 10)
      .then((result) => {
        if (!ignore) {
          setPreview(result);
        }
      })
      .catch((err: Error) => {
        if (!ignore) {
          setPreview(null);
          setPreviewError(formatError(err.message));
        }
      })
      .finally(() => {
        if (!ignore) {
          setPreviewLoading(false);
        }
      });

    return () => {
      ignore = true;
    };
  }, [selectedTable?.schema, selectedTable?.table, selectedTable?.error]);

  async function refreshStatus() {
    const [nextHealth, nextConfig] = await Promise.all([getHealth(), getRuntimeConfig()]);
    setHealth(nextHealth);
    setRuntimeConfig(nextConfig);
    setConfigForm(configToForm(nextConfig));
  }

  function handleConfigFormChange(nextForm: ConfigForm) {
    setConfigForm(nextForm);
    setSaveState("idle");
  }

  async function handleQuery() {
    const question = draft.trim();
    if (!question || busy) {
      return;
    }

    const userMessage: ChatMessage = { id: createId(), role: "user", content: question };
    setMessages((items) => [...items, userMessage]);
    setDraft("");
    setBusy(true);
    setError(null);

    try {
      const agent = await queryAgent(question, language);
      setMessages((items) => [
        ...items,
        {
          id: createId(),
          role: "assistant",
          content: agent.answer || text.noRows,
          agent
        }
      ]);
      setHealth(await getHealth());
    } catch (err) {
      const message = err instanceof Error ? formatError(err.message) : String(err);
      setMessages((items) => [...items, { id: createId(), role: "assistant", content: message, error: true }]);
      setError(message);
    } finally {
      setBusy(false);
    }
  }

  async function handleConfigSave(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSavingConfig(true);
    setSaveState("idle");
    setError(null);
    try {
      const nextConfig = await updateRuntimeConfig(formToPayload(configForm));
      setRuntimeConfig(nextConfig);
      setConfigForm(configToForm(nextConfig));
      setHealth(await getHealth());
      setSaveState("saved");
    } catch (err) {
      setError(err instanceof Error ? formatError(err.message) : String(err));
    } finally {
      setSavingConfig(false);
    }
  }

  async function handleConfigTest(target: ConfigTestTarget) {
    setTestingConfig(target);
    setError(null);
    setConfigTestResult((items) => ({ ...items, [target]: undefined }));
    try {
      const payload = formToPayload(configForm);
      const result = target === "database" ? await testDatabaseConfig(payload) : await testLlmConfig(payload);
      setConfigTestResult((items) => ({ ...items, [target]: result }));
      if (target === "model") {
        setHealth(await getHealth());
      }
    } catch (err) {
      const message = err instanceof Error ? formatError(err.message) : String(err);
      setConfigTestResult((items) => ({ ...items, [target]: { ok: false, message, latency_ms: null, detail: {} } }));
    } finally {
      setTestingConfig(null);
    }
  }

  async function handleCollectMetadata() {
    setMetadataLoading(true);
    setMetadataError(null);
    setPreviewError(null);
    try {
      const schemaLimit = optionalNumber(configForm.pg_schema_limit);
      const result = await getSchemaMetadata(schemaLimit);
      setMetadata(result);
      setSelectedTableId((current) => {
        if (current && result.tables.some((item) => tableKey(item) === current)) {
          return current;
        }
        const firstHealthyTable = result.tables.find((item) => !item.error) ?? result.tables[0] ?? null;
        return firstHealthyTable ? tableKey(firstHealthyTable) : null;
      });
    } catch (err) {
      const message = err instanceof Error ? formatError(err.message) : String(err);
      setMetadataError(message);
      setError(message);
    } finally {
      setMetadataLoading(false);
    }
  }

  function startPaneResize(event: ReactPointerEvent<HTMLDivElement>) {
    const workspace = workspaceRef.current;
    if (!workspace) {
      return;
    }
    const { width } = workspace.getBoundingClientRect();
    if (width <= 0) {
      return;
    }

    event.preventDefault();
    const startX = event.clientX;
    const startSizes = paneSizes;

    function onPointerMove(moveEvent: PointerEvent) {
      const deltaPercent = ((moveEvent.clientX - startX) / width) * 100;
      setPaneSizes(resizePanePair(startSizes, deltaPercent));
    }

    function onPointerUp() {
      window.removeEventListener("pointermove", onPointerMove);
      window.removeEventListener("pointerup", onPointerUp);
    }

    window.addEventListener("pointermove", onPointerMove);
    window.addEventListener("pointerup", onPointerUp);
  }

  function handleComposerSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    void handleQuery();
  }

  function handleComposerKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      void handleQuery();
    }
  }

  function applyExample(example: string) {
    setDraft(example);
  }

  return (
    <main className="app-shell">
      <header className="topbar">
        <div className="brand-block">
          <div className="brand-icon">
            <Bot size={22} />
          </div>
          <div>
            <h1>{text.title}</h1>
            <p>{text.subtitle}</p>
          </div>
        </div>
        <div className="top-actions">
          <SettingsBar onOpen={() => setSettingsOpen(true)} text={text} />
          <LanguageToggle language={language} onChange={setLanguage} />
          <StatusPill ok={Boolean(health?.database_configured)} label={health?.database_configured ? text.dbReady : text.dbMissing} icon="db" />
          <StatusPill ok={Boolean(health?.llm_configured)} label={health?.llm_configured ? text.llmReady : text.llmMissing} icon="spark" />
        </div>
      </header>

      {error && (
        <div className="error-banner">
          <AlertTriangle size={18} />
          <span>{error}</span>
        </div>
      )}

      <section
        className="workspace-grid resizable-workspace"
        ref={workspaceRef}
        style={{ gridTemplateColumns: `${paneSizes[0]}% 8px ${paneSizes[1]}%` }}
      >
        <section className="workspace-pane data-pane">
          <DataExplorerPanel
            metadata={metadata}
            selectedTable={selectedTable}
            selectedTableId={selectedTableId}
            tableFilter={tableFilter}
            preview={preview}
            loading={metadataLoading}
            previewLoading={previewLoading}
            metadataError={metadataError}
            previewError={previewError}
            onCollect={handleCollectMetadata}
            onFilterChange={setTableFilter}
            onSelectTable={setSelectedTableId}
            text={text}
          />
        </section>

        <ResizeHandle onPointerDown={startPaneResize} />

        <section className="workspace-pane agent-pane">
          <section className="panel chat-panel">
            <div className="chat-messages" ref={messagesRef}>
              {messages.length === 0 && (
                <div className="empty-chat">
                  <p>{text.emptyChat}</p>
                  <div className="example-row inline">
                    {text.examples.map((example) => (
                      <button className="chip-button" key={example} onClick={() => applyExample(example)}>
                        {example}
                      </button>
                    ))}
                  </div>
                </div>
              )}
              {messages.map((message) => (
                <ChatMessageView key={message.id} message={message} text={text} />
              ))}
              {busy && (
                <div className="message assistant">
                  <div className="message-avatar">
                    <Loader2 className="spin" size={16} />
                  </div>
                  <div className="message-body">
                    <div className="message-meta">Agent</div>
                    <div className="message-bubble">{text.sending}</div>
                  </div>
                </div>
              )}
            </div>

            <form className="chat-composer" onSubmit={handleComposerSubmit}>
              <textarea
                value={draft}
                onChange={(event) => setDraft(event.target.value)}
                onKeyDown={handleComposerKeyDown}
                placeholder={text.placeholder}
                rows={2}
              />
              <button className="primary-button send-button" type="submit" disabled={busy || draft.trim().length === 0}>
                {busy ? <Loader2 className="spin" size={17} /> : <Send size={17} />}
                <span>{busy ? text.sending : text.send}</span>
              </button>
            </form>
          </section>
        </section>
      </section>

      {settingsOpen && (
        <SettingsModal text={text} onClose={() => setSettingsOpen(false)}>
          <SettingsPanel
            form={configForm}
            runtimeConfig={runtimeConfig}
            onChange={handleConfigFormChange}
            onSubmit={handleConfigSave}
            saving={savingConfig}
            saveState={saveState}
            activeTab={settingsTab}
            onTabChange={setSettingsTab}
            onTest={handleConfigTest}
            testingTarget={testingConfig}
            testResult={configTestResult}
            text={text}
          />
        </SettingsModal>
      )}
    </main>
  );
}

function ChatMessageView({ message, text }: { message: ChatMessage; text: CopyText }) {
  const isAssistant = message.role === "assistant";
  return (
    <div className={`message ${message.role} ${message.error ? "error" : ""}`}>
      {isAssistant && (
        <div className="message-avatar">
          <Bot size={16} />
        </div>
      )}
      <div className="message-body">
        <div className="message-meta">
          {isAssistant ? "Agent" : "You"}
          {message.agent && <span>{formatUsage(message.agent.token_usage, text)}</span>}
        </div>
        <div className="message-bubble">
          <MessageContent content={message.content} />
          {message.agent && <AgentArtifacts agent={message.agent} text={text} />}
        </div>
      </div>
    </div>
  );
}

function AgentArtifacts({ agent, text }: { agent: AgentResponse; text: CopyText }) {
  const rawSchemaTables = agent.schema?.tables;
  const schemaTables = Array.isArray(rawSchemaTables) ? rawSchemaTables.slice(0, 8) : [];
  return (
    <div className="agent-artifacts">
      <details className="agent-detail">
        <summary>{text.answerDetails}</summary>
        {agent.result && <InlineResultTable result={agent.result} text={text} />}
        {agent.sql ? <pre className="sql-preview inline">{agent.sql}</pre> : <p className="empty-state slim">{text.emptySql}</p>}
        <div className="agent-detail-grid">
          <div>
            <strong>{text.agentTrace}</strong>
            {agent.trace.length === 0 && <p className="empty-state slim">{text.emptyTrace}</p>}
            {agent.trace.slice(0, 6).map((step, index) => (
              <p className="compact-line" key={`${step.name}-${index}`}>
                {step.name}: {step.summary}
              </p>
            ))}
          </div>
          <div>
            <strong>{text.businessRules}</strong>
            {agent.rules.length === 0 && <p className="empty-state slim">{text.emptyRules}</p>}
            {agent.rules.slice(0, 4).map((rule) => (
              <p className="compact-line" key={rule.path}>{rule.path}</p>
            ))}
          </div>
          <div>
            <strong>{text.schema}</strong>
            {schemaTables.length === 0 && <p className="empty-state slim">{text.emptySchema}</p>}
            {schemaTables.map((item, index) => (
              <p className="compact-line" key={`${String(item.schema)}-${String(item.table)}-${index}`}>
                {String(item.schema)}.{String(item.table)}
              </p>
            ))}
          </div>
        </div>
      </details>
    </div>
  );
}

function MessageContent({ content }: { content: string }) {
  const lines = content.replace(/\r\n/g, "\n").split("\n");
  const blocks = [];
  let index = 0;

  while (index < lines.length) {
    const line = lines[index];
    const trimmed = line.trim();
    if (!trimmed) {
      index += 1;
      continue;
    }

    if (trimmed.startsWith("```")) {
      const codeLines: string[] = [];
      index += 1;
      while (index < lines.length && !lines[index].trim().startsWith("```")) {
        codeLines.push(lines[index]);
        index += 1;
      }
      index += 1;
      blocks.push(
        <pre className="message-code" key={`code-${index}`}>
          <code>{codeLines.join("\n")}</code>
        </pre>
      );
      continue;
    }

    if (isMarkdownTable(lines, index)) {
      const tableLines: string[] = [];
      while (index < lines.length && isMarkdownRow(lines[index])) {
        tableLines.push(lines[index]);
        index += 1;
      }
      const headers = splitMarkdownRow(tableLines[0]);
      const rows = tableLines.slice(2).map(splitMarkdownRow);
      blocks.push(
        <div className="message-table-wrap" key={`table-${index}`}>
          <table className="message-table">
            <thead>
              <tr>
                {headers.map((header, headerIndex) => (
                  <th key={`${header}-${headerIndex}`}>{renderInlineMarkdown(header)}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((row, rowIndex) => (
                <tr key={rowIndex}>
                  {headers.map((_, cellIndex) => (
                    <td key={cellIndex}>{renderInlineMarkdown(row[cellIndex] ?? "")}</td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      );
      continue;
    }

    if (/^[-*]\s+/.test(trimmed)) {
      const items: string[] = [];
      while (index < lines.length && /^[-*]\s+/.test(lines[index].trim())) {
        items.push(lines[index].trim().replace(/^[-*]\s+/, ""));
        index += 1;
      }
      blocks.push(
        <ul className="message-list" key={`ul-${index}`}>
          {items.map((item, itemIndex) => (
            <li key={itemIndex}>{renderInlineMarkdown(item)}</li>
          ))}
        </ul>
      );
      continue;
    }

    if (/^\d+[.)]\s+/.test(trimmed)) {
      const items: string[] = [];
      while (index < lines.length && /^\d+[.)]\s+/.test(lines[index].trim())) {
        items.push(lines[index].trim().replace(/^\d+[.)]\s+/, ""));
        index += 1;
      }
      blocks.push(
        <ol className="message-list" key={`ol-${index}`}>
          {items.map((item, itemIndex) => (
            <li key={itemIndex}>{renderInlineMarkdown(item)}</li>
          ))}
        </ol>
      );
      continue;
    }

    const paragraph: string[] = [];
    while (
      index < lines.length &&
      lines[index].trim() &&
      !lines[index].trim().startsWith("```") &&
      !isMarkdownTable(lines, index) &&
      !/^[-*]\s+/.test(lines[index].trim()) &&
      !/^\d+[.)]\s+/.test(lines[index].trim())
    ) {
      paragraph.push(lines[index]);
      index += 1;
    }
    blocks.push(<p key={`p-${index}`}>{renderInlineMarkdown(paragraph.join("\n"))}</p>);
  }

  return <div className="message-content">{blocks}</div>;
}

function isMarkdownTable(lines: string[], index: number) {
  const current = lines[index]?.trim() ?? "";
  const next = lines[index + 1]?.trim() ?? "";
  const columns = splitMarkdownRow(current);
  return isMarkdownRow(current) && columns.length > 0 && isMarkdownDivider(next, columns.length);
}

function isMarkdownRow(row: string) {
  const trimmed = row.trim();
  return trimmed.includes("|") && (trimmed.startsWith("|") || trimmed.endsWith("|"));
}

function isMarkdownDivider(row: string, columnCount: number) {
  const cells = splitMarkdownRow(row);
  return cells.length === columnCount && cells.every((cell) => /^:?-{3,}:?$/.test(cell));
}

function splitMarkdownRow(row: string) {
  return row
    .trim()
    .replace(/^\|/, "")
    .replace(/\|$/, "")
    .split("|")
    .map((cell) => cell.trim());
}

function renderInlineMarkdown(text: string) {
  const nodes: Array<string | JSX.Element> = [];
  const pattern = /(`[^`]+`|\*\*[^*]+\*\*)/g;
  let lastIndex = 0;
  let match: RegExpExecArray | null;

  while ((match = pattern.exec(text)) !== null) {
    if (match.index > lastIndex) {
      nodes.push(text.slice(lastIndex, match.index));
    }

    const token = match[0];
    const key = `${match.index}-${token}`;
    if (token.startsWith("`")) {
      nodes.push(<code key={key}>{token.slice(1, -1)}</code>);
    } else {
      nodes.push(<strong key={key}>{token.slice(2, -2)}</strong>);
    }
    lastIndex = pattern.lastIndex;
  }

  if (lastIndex < text.length) {
    nodes.push(text.slice(lastIndex));
  }
  return nodes;
}

function SettingsBar({
  onOpen,
  text
}: {
  onOpen: () => void;
  text: CopyText;
}) {
  return (
    <button className="settings-bar" type="button" onClick={onOpen} aria-label={text.openSettings}>
      <Settings size={17} />
      <span>{text.settings}</span>
    </button>
  );
}

function SettingsModal({ children, onClose, text }: { children: JSX.Element; onClose: () => void; text: CopyText }) {
  return (
    <div
      className="modal-backdrop"
      role="dialog"
      aria-modal="true"
      aria-label={text.settings}
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) {
          onClose();
        }
      }}
    >
      <div className="settings-dialog">
        <button className="icon-button modal-close" type="button" aria-label={text.closeSettings} onClick={onClose}>
          <X size={18} />
        </button>
        {children}
      </div>
    </div>
  );
}

function LanguageToggle({ language, onChange }: { language: UiLanguage; onChange: (language: UiLanguage) => void }) {
  return (
    <div className="language-toggle" aria-label="Language">
      <Languages size={15} />
      <button className={language === "zh" ? "active" : ""} onClick={() => onChange("zh")}>
        中
      </button>
      <button className={language === "en" ? "active" : ""} onClick={() => onChange("en")}>
        EN
      </button>
    </div>
  );
}

function StatusPill({ ok, label, icon }: { ok: boolean; label: string; icon: "db" | "spark" }) {
  return (
    <div className={`status-pill ${ok ? "ok" : "warn"}`}>
      {icon === "db" ? <Database size={15} /> : <Sparkles size={15} />}
      <span>{label}</span>
    </div>
  );
}

function ResizeHandle({ onPointerDown }: { onPointerDown: (event: ReactPointerEvent<HTMLDivElement>) => void }) {
  return (
    <div className="pane-resizer" onPointerDown={onPointerDown} role="separator" aria-orientation="vertical">
      <GripVertical size={16} />
    </div>
  );
}

function DataExplorerPanel({
  metadata,
  selectedTable,
  selectedTableId,
  tableFilter,
  preview,
  loading,
  previewLoading,
  metadataError,
  previewError,
  onCollect,
  onFilterChange,
  onSelectTable,
  text
}: {
  metadata: SchemaMetadataResponse | null;
  selectedTable: TableMetadata | null;
  selectedTableId: string | null;
  tableFilter: string;
  preview: QueryResult | null;
  loading: boolean;
  previewLoading: boolean;
  metadataError: string | null;
  previewError: string | null;
  onCollect: () => void;
  onFilterChange: (value: string) => void;
  onSelectTable: (tableId: string) => void;
  text: CopyText;
}) {
  const filteredTables = useMemo(() => {
    const tables = metadata?.tables ?? [];
    const keyword = tableFilter.trim().toLowerCase();
    if (!keyword) {
      return tables;
    }
    return tables.filter((item) => `${item.schema}.${item.table}`.toLowerCase().includes(keyword));
  }, [metadata, tableFilter]);

  const columns = selectedTable?.columns ?? [];
  const indexes = selectedTable?.indexes ?? [];

  return (
    <section className="panel data-panel">
      <div className="panel-header">
        <div>
          <h2>{text.dataExplorer}</h2>
          <span>
            {metadata
              ? `${text.metadataReady}: ${metadata.table_count} / ${text.failedTables}: ${metadata.failed_count} / ${metadata.statement_timeout_ms}ms`
              : text.metadataSafety}
          </span>
        </div>
        <button className="secondary-button header-button" type="button" disabled={loading} onClick={onCollect}>
          {loading ? <Loader2 className="spin" size={16} /> : <RefreshCw size={16} />}
          <span>{loading ? text.collectingMetadata : text.collectMetadata}</span>
        </button>
      </div>

      <div className="data-toolbar">
        <label className="table-search">
          <Search size={15} />
          <input value={tableFilter} placeholder={text.tableSearch} onChange={(event) => onFilterChange(event.target.value)} />
        </label>
      </div>

      {metadataError && (
        <div className="inline-alert">
          <AlertTriangle size={16} />
          <span>{text.metadataFailed}: {metadataError}</span>
        </div>
      )}

      {!metadata && !loading && !metadataError && <p className="empty-state">{text.metadataEmpty}</p>}

      {metadata && (
        <div className="data-explorer-body">
          <div className="table-list" aria-label={text.schema}>
            {filteredTables.map((item) => {
              const key = tableKey(item);
              return (
                <button
                  className={`table-list-item ${selectedTableId === key ? "active" : ""} ${item.error ? "error" : ""}`}
                  key={key}
                  type="button"
                  onClick={() => onSelectTable(key)}
                >
                  <strong>{item.table}</strong>
                  <span>{item.schema}</span>
                  <small>
                    {text.estimatedRows}: {formatOptionalNumber(item.estimated_rows)}
                  </small>
                </button>
              );
            })}
            {filteredTables.length === 0 && <p className="empty-state slim">{text.emptySchema}</p>}
          </div>

          <div className="table-detail">
            {!selectedTable && <p className="empty-state">{text.noTableSelected}</p>}
            {selectedTable && (
              <>
                <div className="table-detail-header">
                  <div>
                    <h3>
                      {selectedTable.schema}.{selectedTable.table}
                    </h3>
                    <span>
                      {text.tableType}: {selectedTable.table_type ?? "-"} / {text.estimatedRows}:{" "}
                      {formatOptionalNumber(selectedTable.estimated_rows)}
                    </span>
                  </div>
                  {selectedTable.error ? <AlertTriangle size={18} /> : <Table2 size={18} />}
                </div>

                {selectedTable.error && (
                  <div className="inline-alert">
                    <AlertTriangle size={16} />
                    <span>{selectedTable.error}</span>
                  </div>
                )}

                <section className="metadata-section">
                  <div className="metadata-title">
                    <Columns3 size={15} />
                    <strong>
                      {text.columns} ({columns.length})
                    </strong>
                  </div>
                  <div className="column-list">
                    {columns.map((column, index) => (
                      <div className="column-item" key={`${metadataValue(column, "column_name")}-${index}`}>
                        <strong>{metadataValue(column, "column_name")}</strong>
                        <span>{metadataValue(column, "data_type")}</span>
                        <small>{metadataValue(column, "is_nullable") === "YES" ? "nullable" : "not null"}</small>
                      </div>
                    ))}
                    {columns.length === 0 && <p className="empty-state slim">{text.emptySchema}</p>}
                  </div>
                </section>

                <section className="metadata-section">
                  <div className="metadata-title">
                    <Table2 size={15} />
                    <strong>{text.previewRows}</strong>
                  </div>
                  {previewLoading && (
                    <div className="loading-row">
                      <Loader2 className="spin" size={16} />
                      <span>{text.previewLoading}</span>
                    </div>
                  )}
                  {previewError && !previewLoading && (
                    <div className="inline-alert">
                      <AlertTriangle size={16} />
                      <span>{previewError}</span>
                    </div>
                  )}
                  {preview && !previewLoading && <PreviewResultTable result={preview} text={text} />}
                </section>

                <details className="metadata-details">
                  <summary>
                    {text.indexes} ({indexes.length})
                  </summary>
                  <div className="index-list">
                    {indexes.map((index, itemIndex) => (
                      <pre key={`${metadataValue(index, "indexname")}-${itemIndex}`}>{metadataValue(index, "indexdef")}</pre>
                    ))}
                    {indexes.length === 0 && <p className="empty-state slim">{text.noRows}</p>}
                  </div>
                </details>
              </>
            )}
          </div>
        </div>
      )}
    </section>
  );
}

function SettingsPanel({
  form,
  runtimeConfig,
  onChange,
  onSubmit,
  saving,
  saveState,
  activeTab,
  onTabChange,
  onTest,
  testingTarget,
  testResult,
  text
}: {
  form: ConfigForm;
  runtimeConfig: RuntimeConfigResponse | null;
  onChange: (form: ConfigForm) => void;
  onSubmit: (event: FormEvent<HTMLFormElement>) => void;
  saving: boolean;
  saveState: "idle" | "saved";
  activeTab: "database" | "model" | "runtime";
  onTabChange: (tab: "database" | "model" | "runtime") => void;
  onTest: (target: ConfigTestTarget) => void;
  testingTarget: ConfigTestTarget | null;
  testResult: Partial<Record<ConfigTestTarget, ConfigTestResponse>>;
  text: CopyText;
}) {
  function setField<K extends keyof ConfigForm>(field: K, value: ConfigForm[K]) {
    onChange({ ...form, [field]: value });
  }

  return (
    <section className="panel settings-panel">
      <div className="panel-header compact">
        <div>
          <h2>{text.settings}</h2>
        </div>
        <Settings size={16} />
      </div>
      <form className="settings-form" onSubmit={onSubmit}>
        <div className="settings-tabs" aria-label={text.settings}>
          <button type="button" className={activeTab === "database" ? "active" : ""} onClick={() => onTabChange("database")}>
            <Database size={14} />
            {text.settingsDatabase}
          </button>
          <button type="button" className={activeTab === "model" ? "active" : ""} onClick={() => onTabChange("model")}>
            <KeyRound size={14} />
            {text.settingsModel}
          </button>
          <button type="button" className={activeTab === "runtime" ? "active" : ""} onClick={() => onTabChange("runtime")}>
            <Clock3 size={14} />
            {text.settingsRuntime}
          </button>
        </div>

        {activeTab === "database" && (
          <fieldset>
            <legend>
              <Database size={14} />
              {text.connection}
            </legend>
          <div className="form-grid two">
            <Field label={text.host} value={form.db_host} onChange={(value) => setField("db_host", value)} />
            <Field label={text.port} value={form.db_port} type="number" onChange={(value) => setField("db_port", value)} />
          </div>
          <Field label={text.dbName} value={form.db_name} onChange={(value) => setField("db_name", value)} />
          <Field label={text.dbUser} value={form.db_user} onChange={(value) => setField("db_user", value)} />
          <Field
            label={text.dbPassword}
            value={form.db_password}
            type="password"
            placeholder={runtimeConfig?.database.password_configured ? text.secretPlaceholder : ""}
            onChange={(value) => setField("db_password", value)}
          />
          <Field label={text.sslmode} value={form.db_sslmode} onChange={(value) => setField("db_sslmode", value)} />
          </fieldset>
        )}

        {activeTab === "model" && (
          <fieldset>
            <legend>
              <KeyRound size={14} />
              {text.model}
            </legend>
            <Field label={text.provider} value={form.llm_provider} onChange={(value) => setField("llm_provider", value)} />
            <Field label={text.baseUrl} value={form.llm_base_url} onChange={(value) => setField("llm_base_url", value)} />
            <Field label={text.modelName} value={form.llm_model} onChange={(value) => setField("llm_model", value)} />
            <Field
              label={text.apiKey}
              value={form.llm_api_key}
              type="password"
              placeholder={runtimeConfig?.llm.api_key_configured ? text.secretPlaceholder : ""}
              onChange={(value) => setField("llm_api_key", value)}
            />
            <Field label="Timeout(s)" value={form.llm_timeout_seconds} type="number" onChange={(value) => setField("llm_timeout_seconds", value)} />
          </fieldset>
        )}

        {activeTab === "runtime" && (
          <fieldset>
            <legend>
              <Clock3 size={14} />
              {text.runContext}
            </legend>
          <Field label={text.timezone} value={form.app_timezone} onChange={(value) => setField("app_timezone", value)} />
          <div className="form-grid two">
            <Field label={text.maxRows} value={form.pg_max_rows} type="number" onChange={(value) => setField("pg_max_rows", value)} />
            <Field label={text.schemaLimit} value={form.pg_schema_limit} type="number" onChange={(value) => setField("pg_schema_limit", value)} />
          </div>
          <Field
            label={text.statementTimeout}
            value={form.pg_statement_timeout_ms}
            type="number"
            onChange={(value) => setField("pg_statement_timeout_ms", value)}
          />
          </fieldset>
        )}

        {activeTab !== "runtime" && (
          <TestStatus result={activeTab === "database" ? testResult.database : testResult.model} />
        )}

        <div className={`config-actions ${activeTab === "runtime" ? "single" : ""}`}>
          {activeTab === "database" && (
            <button
              className="secondary-button"
              type="button"
              disabled={Boolean(testingTarget) || saving}
              onClick={() => onTest("database")}
            >
              {testingTarget === "database" ? <Loader2 className="spin" size={16} /> : <Search size={16} />}
              {testingTarget === "database" ? text.testing : text.testConnection}
            </button>
          )}
          {activeTab === "model" && (
            <button
              className="secondary-button"
              type="button"
              disabled={Boolean(testingTarget) || saving}
              onClick={() => onTest("model")}
            >
              {testingTarget === "model" ? <Loader2 className="spin" size={16} /> : <Sparkles size={16} />}
              {testingTarget === "model" ? text.testing : text.testModel}
            </button>
          )}
          <button className="primary-button full-button" type="submit" disabled={saving || Boolean(testingTarget)}>
            {saving ? <Loader2 className="spin" size={16} /> : saveState === "saved" ? <CheckCircle2 size={16} /> : <Save size={16} />}
            {saving ? text.saving : saveState === "saved" ? text.saved : text.save}
          </button>
        </div>
      </form>
    </section>
  );
}

function TestStatus({ result }: { result: ConfigTestResponse | undefined }) {
  if (!result) {
    return null;
  }
  return (
    <div className={`test-status ${result.ok ? "ok" : "error"}`}>
      {result.ok ? <CheckCircle2 size={15} /> : <AlertTriangle size={15} />}
      <span>
        {result.message}
        {result.latency_ms !== null && result.latency_ms !== undefined ? ` (${result.latency_ms}ms)` : ""}
      </span>
    </div>
  );
}

function Field({
  label,
  value,
  onChange,
  type = "text",
  placeholder = ""
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  type?: "text" | "password" | "number";
  placeholder?: string;
}) {
  return (
    <label className="field">
      <span>{label}</span>
      <input value={value} type={type} placeholder={placeholder} onChange={(event) => onChange(event.target.value)} />
    </label>
  );
}

function TokenPanel({
  current,
  session,
  server,
  text
}: {
  current: TokenUsage;
  session: TokenUsage;
  server: TokenUsage;
  text: CopyText;
}) {
  return (
    <section className="panel token-panel">
      <div className="panel-header compact">
        <div>
          <h2>{text.tokenUsage}</h2>
          <span>
            {text.total}: {formatNumber(session.total_tokens)}
          </span>
        </div>
        <Sparkles size={16} />
      </div>
      <div className="usage-grid">
        <UsageCard label={text.currentQuery} usage={current} text={text} />
        <UsageCard label={text.session} usage={session} text={text} />
        <UsageCard label={text.serverTotal} usage={server} text={text} />
      </div>
    </section>
  );
}

function UsageCard({ label, usage, text }: { label: string; usage: TokenUsage; text: CopyText }) {
  return (
    <div className="usage-card">
      <strong>{label}</strong>
      <span>
        {text.total}: {formatNumber(usage.total_tokens)}
      </span>
      <small>
        {text.prompt} {formatNumber(usage.prompt_tokens)} / {text.completion} {formatNumber(usage.completion_tokens)} / {text.requests}{" "}
        {formatNumber(usage.requests)}
      </small>
    </div>
  );
}

function RunContext({ health, text }: { health: HealthResponse | null; text: CopyText }) {
  return (
    <section className="panel context-panel">
      <div className="panel-header compact">
        <div>
          <h2>{text.runContext}</h2>
          <span>{health?.app_timezone ?? "Asia/Shanghai"}</span>
        </div>
        <ShieldCheck size={16} />
      </div>
      <div className="context-item">
        <ShieldCheck size={16} />
        <div>
          <strong>{text.readonly}</strong>
          <span>SELECT / WITH</span>
        </div>
      </div>
      <div className="context-item">
        <Clock3 size={16} />
        <div>
          <strong>{text.timezone}</strong>
          <span>{health?.app_timezone ?? "Asia/Shanghai"}</span>
        </div>
      </div>
      <div className="context-item">
        <Settings size={16} />
        <div>
          <strong>{health?.llm_model || "LLM_MODEL"}</strong>
          <span>{health?.llm_provider ?? "manual"}</span>
        </div>
      </div>
    </section>
  );
}

function TracePanel({ trace, text }: { trace: TraceStep[]; text: CopyText }) {
  return (
    <section className="panel">
      <div className="panel-header compact">
        <div>
          <h2>{text.agentTrace}</h2>
          <span>
            {trace.length} {text.requests}
          </span>
        </div>
        <Search size={16} />
      </div>
      <div className="trace-list">
        {trace.length === 0 && <p className="empty-state">{text.emptyTrace}</p>}
        {trace.map((step, index) => (
          <div className={`trace-item ${step.status}`} key={`${step.name}-${index}`}>
            <div className="trace-dot" />
            <div>
              <strong>{step.name}</strong>
              <p>{step.summary}</p>
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}

function SqlPanel({ sql, text }: { sql: string; text: CopyText }) {
  return (
    <section className="panel">
      <div className="panel-header compact">
        <div>
          <h2>{text.auditSql}</h2>
          <span>PostgreSQL</span>
        </div>
        <TerminalSquare size={16} />
      </div>
      {sql ? <pre className="sql-preview">{sql}</pre> : <p className="empty-state">{text.emptySql}</p>}
    </section>
  );
}

function RulesPanel({ agent, text }: { agent: AgentResponse | null; text: CopyText }) {
  const rules = agent?.rules ?? [];
  return (
    <section className="panel">
      <div className="panel-header compact">
        <div>
          <h2>{text.businessRules}</h2>
          <span>{rules.length}</span>
        </div>
        <Search size={16} />
      </div>
      <div className="rule-list">
        {rules.length === 0 && <p className="empty-state">{text.emptyRules}</p>}
        {rules.map((rule) => (
          <div className="rule-item" key={rule.path}>
            <strong>{rule.path}</strong>
            {rule.snippets.slice(0, 2).map((snippet) => (
              <p key={`${rule.path}-${snippet.line}`}>
                L{snippet.line}: {snippet.text}
              </p>
            ))}
          </div>
        ))}
      </div>
    </section>
  );
}

function SchemaPanel({ agent, text }: { agent: AgentResponse | null; text: CopyText }) {
  const tables = useMemo(() => {
    const rawTables = agent?.schema?.tables;
    return Array.isArray(rawTables) ? rawTables.slice(0, 8) : [];
  }, [agent]);

  return (
    <section className="panel">
      <div className="panel-header compact">
        <div>
          <h2>{text.schema}</h2>
          <span>{tables.length}</span>
        </div>
        <Database size={16} />
      </div>
      <div className="schema-list">
        {tables.length === 0 && <p className="empty-state">{text.emptySchema}</p>}
        {tables.map((item, index) => (
          <div className="schema-item" key={`${String(item.schema)}-${String(item.table)}-${index}`}>
            <strong>
              {String(item.schema)}.{String(item.table)}
            </strong>
            <span>{Array.isArray(item.columns) ? `${item.columns.length} columns` : ""}</span>
          </div>
        ))}
      </div>
    </section>
  );
}

function PreviewResultTable({ result, text }: { result: QueryResult; text: CopyText }) {
  return (
    <div className="preview-result">
      <div className="inline-result-title">
        <Table2 size={15} />
        <strong>{text.tablePreview}</strong>
        <span>
          {result.row_count} {text.rows}
        </span>
      </div>
      <div className="table-wrap preview-table-wrap">
        <table>
          <thead>
            <tr>
              {result.columns.map((column) => (
                <th key={column}>{column}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {result.rows.map((row, rowIndex) => (
              <tr key={rowIndex}>
                {result.columns.map((column) => (
                  <td key={column}>{formatCell(row[column])}</td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function InlineResultTable({ result, text }: { result: QueryResult; text: CopyText }) {
  return (
    <div className="inline-result">
      <div className="inline-result-title">
        <Table2 size={15} />
        <strong>{text.resultTable}</strong>
        <span>
          {result.row_count} {text.rows}
        </span>
      </div>
      <div className="table-wrap compact">
        <table>
          <thead>
            <tr>
              {result.columns.map((column) => (
                <th key={column}>{column}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {result.rows.map((row, rowIndex) => (
              <tr key={rowIndex}>
                {result.columns.map((column) => (
                  <td key={column}>{formatCell(row[column])}</td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function emptyConfigForm(): ConfigForm {
  return {
    app_timezone: "Asia/Shanghai",
    pg_max_rows: "200",
    pg_statement_timeout_ms: "5000",
    pg_schema_limit: "80",
    llm_provider: "",
    llm_base_url: "",
    llm_model: "",
    llm_api_key: "",
    llm_timeout_seconds: "45",
    db_host: "",
    db_port: "",
    db_name: "",
    db_user: "",
    db_password: "",
    db_sslmode: ""
  };
}

function configToForm(config: RuntimeConfigResponse): ConfigForm {
  return {
    app_timezone: config.app_timezone,
    pg_max_rows: String(config.pg_max_rows),
    pg_statement_timeout_ms: String(config.pg_statement_timeout_ms),
    pg_schema_limit: String(config.pg_schema_limit),
    llm_provider: config.llm.provider,
    llm_base_url: config.llm.base_url ?? "",
    llm_model: config.llm.model ?? "",
    llm_api_key: "",
    llm_timeout_seconds: String(config.llm.timeout_seconds),
    db_host: config.database.host ?? "",
    db_port: config.database.port ? String(config.database.port) : "",
    db_name: config.database.database ?? "",
    db_user: config.database.username ?? "",
    db_password: "",
    db_sslmode: config.database.sslmode ?? ""
  };
}

function formToPayload(form: ConfigForm): RuntimeConfigUpdate {
  const payload: RuntimeConfigUpdate = {};

  const appTimezone = form.app_timezone.trim();
  if (appTimezone) {
    payload.app_timezone = appTimezone;
  }

  const pgMaxRows = optionalNumber(form.pg_max_rows);
  if (pgMaxRows !== undefined) {
    payload.pg_max_rows = pgMaxRows;
  }

  const pgStatementTimeoutMs = optionalNumber(form.pg_statement_timeout_ms);
  if (pgStatementTimeoutMs !== undefined) {
    payload.pg_statement_timeout_ms = pgStatementTimeoutMs;
  }

  const pgSchemaLimit = optionalNumber(form.pg_schema_limit);
  if (pgSchemaLimit !== undefined) {
    payload.pg_schema_limit = pgSchemaLimit;
  }

  const llmProvider = form.llm_provider.trim();
  if (llmProvider) {
    payload.llm_provider = llmProvider;
  }

  const llmBaseUrl = form.llm_base_url.trim();
  if (llmBaseUrl) {
    payload.llm_base_url = llmBaseUrl;
  }

  const llmModel = form.llm_model.trim();
  if (llmModel) {
    payload.llm_model = llmModel;
  }

  const llmTimeoutSeconds = optionalNumber(form.llm_timeout_seconds);
  if (llmTimeoutSeconds !== undefined) {
    payload.llm_timeout_seconds = llmTimeoutSeconds;
  }

  const hasDatabaseInput = [
    form.db_host,
    form.db_port,
    form.db_name,
    form.db_user,
    form.db_password,
    form.db_sslmode
  ].some((value) => value.trim().length > 0);

  if (hasDatabaseInput) {
    const dbHost = form.db_host.trim();
    if (dbHost) {
      payload.db_host = dbHost;
    }

    const dbPort = optionalNumber(form.db_port);
    if (dbPort !== undefined) {
      payload.db_port = dbPort;
    }

    const dbName = form.db_name.trim();
    if (dbName) {
      payload.db_name = dbName;
    }

    const dbUser = form.db_user.trim();
    if (dbUser) {
      payload.db_user = dbUser;
    }

    const dbSslmode = form.db_sslmode.trim();
    if (dbSslmode) {
      payload.db_sslmode = dbSslmode;
    }
  }

  if (form.llm_api_key.trim()) {
    payload.llm_api_key = form.llm_api_key.trim();
  }
  if (hasDatabaseInput && form.db_password.trim()) {
    payload.db_password = form.db_password.trim();
  }
  return payload;
}

function tableKey(item: Pick<TableMetadata, "schema" | "table">) {
  return JSON.stringify([item.schema, item.table]);
}

function metadataValue(item: Record<string, unknown>, key: string) {
  const value = item[key];
  if (value === null || value === undefined) {
    return "-";
  }
  return String(value);
}

function formatOptionalNumber(value: number | null | undefined) {
  if (value === null || value === undefined) {
    return "-";
  }
  return formatNumber(value);
}

function resizePanePair(
  startSizes: [number, number],
  deltaPercent: number
): [number, number] {
  const next: [number, number] = [...startSizes];
  const minDelta = PANE_MIN_SIZES[0] - next[0];
  const maxDelta = next[1] - PANE_MIN_SIZES[1];
  const appliedDelta = Math.min(Math.max(deltaPercent, minDelta), maxDelta);
  next[0] += appliedDelta;
  next[1] -= appliedDelta;
  return next;
}

function optionalNumber(value: string): number | undefined {
  const trimmed = value.trim();
  if (!trimmed) {
    return undefined;
  }
  const parsed = Number(trimmed);
  return Number.isFinite(parsed) ? parsed : undefined;
}

function addUsage(base: TokenUsage, next: TokenUsage | undefined): TokenUsage {
  if (!next) {
    return base;
  }
  return {
    prompt_tokens: base.prompt_tokens + next.prompt_tokens,
    completion_tokens: base.completion_tokens + next.completion_tokens,
    total_tokens: base.total_tokens + next.total_tokens,
    requests: base.requests + next.requests
  };
}

function formatUsage(usage: TokenUsage, text: CopyText) {
  if (!usage.total_tokens) {
    return `${text.total}: 0`;
  }
  return `${text.total}: ${formatNumber(usage.total_tokens)}`;
}

function formatNumber(value: number) {
  return new Intl.NumberFormat().format(value);
}

function formatCell(value: unknown) {
  if (value === null || value === undefined) {
    return "";
  }
  if (typeof value === "object") {
    return JSON.stringify(value);
  }
  return String(value);
}

function formatError(raw: string) {
  try {
    const parsed = JSON.parse(raw);
    return parsed.detail || raw;
  } catch {
    return raw;
  }
}

function createId() {
  return `${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

export default App;
