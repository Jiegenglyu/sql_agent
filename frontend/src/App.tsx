import { FormEvent, useEffect, useMemo, useState } from "react";
import {
  AlertCircle,
  CheckCircle2,
  Database,
  FileText,
  Loader2,
  Play,
  RefreshCw,
  Save,
  Search,
  Settings,
  Table2,
  TerminalSquare,
  Unplug
} from "lucide-react";

import {
  askPublicMcp,
  describePublicMcpCapabilities,
  getHealth,
  getMcpCalls,
  getRuntimeConfig,
  getSchemaMetadata,
  previewTable,
  testDatabaseConfig,
  testLlmConfig,
  updateRuntimeConfig
} from "./api";
import type {
  ConfigTestResponse,
  HealthResponse,
  McpCallRecord,
  PublicMcpResponse,
  QueryResult,
  RuntimeConfigResponse,
  RuntimeConfigUpdate,
  SchemaMetadataResponse,
  TableMetadata,
  TraceStep,
  UiLanguage
} from "./types";

type PageKey = "settings" | "traces" | "debug";
type BusyKey = "status" | "save" | "test-db" | "test-llm" | "schema" | "preview" | "ask" | "capabilities" | "calls";

interface ConfigForm {
  app_timezone: string;
  pg_max_rows: string;
  pg_statement_timeout_ms: string;
  pg_schema_limit: string;
  pg_schemas: string;
  agent_verbose_debug: boolean;
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

const DEFAULT_QUESTION = "Xlarge 是什么卡？";

function App() {
  const [page, setPage] = useState<PageKey>("settings");
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [config, setConfig] = useState<RuntimeConfigResponse | null>(null);
  const [configForm, setConfigForm] = useState<ConfigForm>(() => emptyConfigForm());
  const [language, setLanguage] = useState<UiLanguage>("zh");
  const [caller, setCaller] = useState("dashboard-debug");
  const [apiKey, setApiKey] = useState(() => localStorage.getItem("mcp_api_key") || "sk-1234");
  const [question, setQuestion] = useState(DEFAULT_QUESTION);
  const [maxRows, setMaxRows] = useState("20");
  const [response, setResponse] = useState<PublicMcpResponse | null>(null);
  const [capabilities, setCapabilities] = useState<Record<string, unknown> | null>(null);
  const [calls, setCalls] = useState<McpCallRecord[]>([]);
  const [selectedCallIndex, setSelectedCallIndex] = useState(0);
  const [metadata, setMetadata] = useState<SchemaMetadataResponse | null>(null);
  const [tableFilter, setTableFilter] = useState("");
  const [selectedTableId, setSelectedTableId] = useState<string | null>(null);
  const [preview, setPreview] = useState<QueryResult | null>(null);
  const [testResult, setTestResult] = useState<Partial<Record<"database" | "llm", ConfigTestResponse>>>({});
  const [busy, setBusy] = useState<BusyKey | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    refreshStatus();
    refreshCalls();
  }, []);

  useEffect(() => {
    if (page !== "traces") {
      return;
    }
    refreshCalls();
    const timer = window.setInterval(refreshCalls, 5000);
    return () => window.clearInterval(timer);
  }, [page]);

  const selectedTable = useMemo(() => {
    if (!metadata || !selectedTableId) {
      return null;
    }
    return metadata.tables.find((item) => tableKey(item) === selectedTableId) ?? null;
  }, [metadata, selectedTableId]);

  const filteredTables = useMemo(() => {
    const tables = metadata?.tables ?? [];
    const filter = tableFilter.trim().toLowerCase();
    if (!filter) {
      return tables;
    }
    return tables.filter((item) => `${item.schema}.${item.table}`.toLowerCase().includes(filter));
  }, [metadata, tableFilter]);

  const selectedCall = calls[selectedCallIndex] ?? calls[0] ?? null;
  const selectedCallResponse = selectedCall?.response as PublicMcpResponse | undefined;
  const debugSourceTables = response?.result?.source_tables ?? extractSchemaTables(response?.schema);

  async function refreshStatus() {
    setBusy("status");
    setError(null);
    try {
      const [nextHealth, nextConfig] = await Promise.all([getHealth(), getRuntimeConfig()]);
      setHealth(nextHealth);
      setConfig(nextConfig);
      setConfigForm(configToForm(nextConfig));
    } catch (err) {
      setError(formatError(err));
    } finally {
      setBusy(null);
    }
  }

  async function refreshCalls() {
    try {
      const result = await getMcpCalls(100);
      setCalls(result.calls);
      setSelectedCallIndex((current) => Math.min(current, Math.max(result.calls.length - 1, 0)));
    } catch (err) {
      if (page === "traces") {
        setError(formatError(err));
      }
    }
  }

  async function saveConfig(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy("save");
    setError(null);
    try {
      const nextConfig = await updateRuntimeConfig(formToPayload(configForm));
      setConfig(nextConfig);
      setConfigForm(configToForm(nextConfig));
      setHealth(await getHealth());
    } catch (err) {
      setError(formatError(err));
    } finally {
      setBusy(null);
    }
  }

  async function runConfigTest(target: "database" | "llm") {
    setBusy(target === "database" ? "test-db" : "test-llm");
    setError(null);
    try {
      const payload = formToPayload(configForm);
      const result = target === "database" ? await testDatabaseConfig(payload) : await testLlmConfig(payload);
      setTestResult((items) => ({ ...items, [target]: result }));
      setHealth(await getHealth());
    } catch (err) {
      const result = { ok: false, message: formatError(err), latency_ms: null, detail: {} };
      setTestResult((items) => ({ ...items, [target]: result }));
    } finally {
      setBusy(null);
    }
  }

  async function loadSchema() {
    setBusy("schema");
    setError(null);
    try {
      const result = await getSchemaMetadata(toInt(configForm.pg_schema_limit), parseSchemaNames(configForm.pg_schemas));
      setMetadata(result);
      const firstHealthy = result.tables.find((item) => !item.error) ?? result.tables[0] ?? null;
      setSelectedTableId(firstHealthy ? tableKey(firstHealthy) : null);
      setPreview(null);
    } catch (err) {
      setError(formatError(err));
    } finally {
      setBusy(null);
    }
  }

  async function loadPreview(table: TableMetadata | null = selectedTable) {
    if (!table || table.error) {
      return;
    }
    setBusy("preview");
    setError(null);
    try {
      setPreview(await previewTable(table.schema, table.table, 10));
    } catch (err) {
      setError(formatError(err));
    } finally {
      setBusy(null);
    }
  }

  async function handleAsk(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy("ask");
    setError(null);
    localStorage.setItem("mcp_api_key", apiKey);
    try {
      const result = await askPublicMcp(question.trim(), apiKey.trim(), caller.trim() || "dashboard-debug", language, toInt(maxRows));
      setResponse(result);
      if (result.capabilities) {
        setCapabilities(result.capabilities);
      }
      refreshCalls();
    } catch (err) {
      setError(formatError(err));
    } finally {
      setBusy(null);
    }
  }

  async function handleCapabilities() {
    setBusy("capabilities");
    setError(null);
    localStorage.setItem("mcp_api_key", apiKey);
    try {
      setCapabilities(await describePublicMcpCapabilities(apiKey.trim(), caller.trim() || "dashboard-debug", language, true));
      refreshCalls();
    } catch (err) {
      setError(formatError(err));
    } finally {
      setBusy(null);
    }
  }

  return (
    <main className="app-layout">
      <aside className="sidebar">
        <div className="brand">
          <Database size={24} />
          <div>
            <strong>SQL Agent</strong>
            <span>MCP Console</span>
          </div>
        </div>
        <nav>
          <NavButton active={page === "settings"} icon={<Settings size={17} />} label="设置与数据源" onClick={() => setPage("settings")} />
          <NavButton active={page === "traces"} icon={<TerminalSquare size={17} />} label="MCP 调用 Trace" onClick={() => setPage("traces")} />
          <NavButton active={page === "debug"} icon={<Play size={17} />} label="调试接口" onClick={() => setPage("debug")} />
        </nav>
        <div className="side-status">
          <StatusLine label="MCP Key" ok={Boolean(health?.mcp_auth_configured)} value={`${health?.mcp_key_count ?? 0}`} />
          <StatusLine label="Database" ok={Boolean(health?.database_configured)} value={config?.database.database || "-"} />
          <StatusLine label="LLM" ok={Boolean(health?.llm_configured)} value={health?.llm_model || "-"} />
        </div>
      </aside>

      <section className="content-shell">
        <header className="content-header">
          <div>
            <h1>{pageTitle(page)}</h1>
            <p>{pageSubtitle(page)}</p>
          </div>
          <button type="button" onClick={page === "traces" ? refreshCalls : refreshStatus} disabled={busy !== null}>
            {busy === "status" || busy === "calls" ? <Loader2 className="spin" size={16} /> : <RefreshCw size={16} />}
            刷新
          </button>
        </header>

        {error ? (
          <div className="error-banner">
            <AlertCircle size={18} />
            {error}
          </div>
        ) : null}

        {page === "settings" ? (
          <SettingsPage
            config={config}
            form={configForm}
            setForm={setConfigForm}
            onSave={saveConfig}
            onTest={runConfigTest}
            testResult={testResult}
            busy={busy}
            metadata={metadata}
            filteredTables={filteredTables}
            tableFilter={tableFilter}
            setTableFilter={setTableFilter}
            selectedTableId={selectedTableId}
            setSelectedTableId={setSelectedTableId}
            selectedTable={selectedTable}
            preview={preview}
            onLoadSchema={loadSchema}
            onPreview={loadPreview}
          />
        ) : null}

        {page === "traces" ? (
          <TracePage calls={calls} selectedIndex={selectedCallIndex} setSelectedIndex={setSelectedCallIndex} selected={selectedCall} response={selectedCallResponse} />
        ) : null}

        {page === "debug" ? (
          <DebugPage
            apiKey={apiKey}
            setApiKey={setApiKey}
            caller={caller}
            setCaller={setCaller}
            question={question}
            setQuestion={setQuestion}
            language={language}
            setLanguage={setLanguage}
            maxRows={maxRows}
            setMaxRows={setMaxRows}
            response={response}
            capabilities={capabilities}
            sourceTables={debugSourceTables}
            busy={busy}
            onAsk={handleAsk}
            onCapabilities={handleCapabilities}
          />
        ) : null}
      </section>
    </main>
  );
}

function SettingsPage(props: {
  config: RuntimeConfigResponse | null;
  form: ConfigForm;
  setForm: (form: ConfigForm) => void;
  onSave: (event: FormEvent<HTMLFormElement>) => void;
  onTest: (target: "database" | "llm") => void;
  testResult: Partial<Record<"database" | "llm", ConfigTestResponse>>;
  busy: BusyKey | null;
  metadata: SchemaMetadataResponse | null;
  filteredTables: TableMetadata[];
  tableFilter: string;
  setTableFilter: (value: string) => void;
  selectedTableId: string | null;
  setSelectedTableId: (value: string) => void;
  selectedTable: TableMetadata | null;
  preview: QueryResult | null;
  onLoadSchema: () => void;
  onPreview: () => void;
}) {
  const update = (patch: Partial<ConfigForm>) => props.setForm({ ...props.form, ...patch });
  return (
    <div className="settings-layout">
      <form className="panel settings-form" onSubmit={props.onSave}>
        <PanelTitle title="系统设置" subtitle="保存后写入本地 .env；密钥留空表示保持不变。" />
        <div className="form-section">
          <h3>LLM</h3>
          <div className="form-grid">
            <Field label="Provider" value={props.form.llm_provider} onChange={(value) => update({ llm_provider: value })} />
            <Field label="Base URL" value={props.form.llm_base_url} onChange={(value) => update({ llm_base_url: value })} />
            <Field label="Model" value={props.form.llm_model} onChange={(value) => update({ llm_model: value })} />
            <Field label="API Key" value={props.form.llm_api_key} onChange={(value) => update({ llm_api_key: value })} type="password" placeholder="留空保持不变" />
            <Field label="Timeout(s)" value={props.form.llm_timeout_seconds} onChange={(value) => update({ llm_timeout_seconds: value })} />
          </div>
          <TestResult result={props.testResult.llm} />
          <button type="button" onClick={() => props.onTest("llm")} disabled={props.busy !== null}>
            {props.busy === "test-llm" ? <Loader2 className="spin" size={16} /> : <Unplug size={16} />}
            测试 LLM
          </button>
        </div>
        <div className="form-section">
          <h3>数据库</h3>
          <div className="form-grid">
            <Field label="Host" value={props.form.db_host} onChange={(value) => update({ db_host: value })} />
            <Field label="Port" value={props.form.db_port} onChange={(value) => update({ db_port: value })} />
            <Field label="Database" value={props.form.db_name} onChange={(value) => update({ db_name: value })} />
            <Field label="User" value={props.form.db_user} onChange={(value) => update({ db_user: value })} />
            <Field label="Password" value={props.form.db_password} onChange={(value) => update({ db_password: value })} type="password" placeholder="留空保持不变" />
            <Field label="SSL Mode" value={props.form.db_sslmode} onChange={(value) => update({ db_sslmode: value })} />
            <Field label="PG Schemas" value={props.form.pg_schemas} onChange={(value) => update({ pg_schemas: value })} />
            <Field label="SQL Timeout(ms)" value={props.form.pg_statement_timeout_ms} onChange={(value) => update({ pg_statement_timeout_ms: value })} />
            <Field label="Schema Limit" value={props.form.pg_schema_limit} onChange={(value) => update({ pg_schema_limit: value })} />
            <Field label="Max Rows" value={props.form.pg_max_rows} onChange={(value) => update({ pg_max_rows: value })} />
          </div>
          <TestResult result={props.testResult.database} />
          <div className="button-row">
            <button type="button" onClick={() => props.onTest("database")} disabled={props.busy !== null}>
              {props.busy === "test-db" ? <Loader2 className="spin" size={16} /> : <Unplug size={16} />}
              测试数据库
            </button>
            <button type="submit" disabled={props.busy !== null}>
              {props.busy === "save" ? <Loader2 className="spin" size={16} /> : <Save size={16} />}
              保存设置
            </button>
          </div>
        </div>
      </form>

      <section className="panel explorer-panel">
        <PanelTitle title="数据库预览" subtitle={props.config?.database.database_url_preview || "加载配置中"} />
        <div className="toolbar">
          <div className="searchbox">
            <Search size={15} />
            <input value={props.tableFilter} onChange={(event) => props.setTableFilter(event.target.value)} placeholder="搜索 schema.table" />
          </div>
          <button type="button" onClick={props.onLoadSchema} disabled={props.busy !== null}>
            {props.busy === "schema" ? <Loader2 className="spin" size={16} /> : <RefreshCw size={16} />}
            收集表
          </button>
        </div>
        <div className="explorer-grid">
          <div className="table-list">
            {props.filteredTables.length ? (
              props.filteredTables.map((table) => (
                <button
                  type="button"
                  key={tableKey(table)}
                  className={props.selectedTableId === tableKey(table) ? "table-item active" : "table-item"}
                  onClick={() => props.setSelectedTableId(tableKey(table))}
                >
                  <strong>{table.table}</strong>
                  <span>{table.schema}</span>
                </button>
              ))
            ) : (
              <div className="empty">点击收集表后预览。</div>
            )}
          </div>
          <div className="preview-pane">
            <div className="preview-header">
              <div>
                <strong>{props.selectedTable ? `${props.selectedTable.schema}.${props.selectedTable.table}` : "未选择表"}</strong>
                <span>{props.selectedTable?.comment || "选择表后可查看字段和前 10 行。"}</span>
              </div>
              <button type="button" onClick={() => props.onPreview()} disabled={props.busy !== null || !props.selectedTable}>
                {props.busy === "preview" ? <Loader2 className="spin" size={16} /> : <Table2 size={16} />}
                预览
              </button>
            </div>
            <ColumnList table={props.selectedTable} />
            <QueryResultTable result={props.preview} />
          </div>
        </div>
      </section>
    </div>
  );
}

function TracePage(props: {
  calls: McpCallRecord[];
  selectedIndex: number;
  setSelectedIndex: (index: number) => void;
  selected: McpCallRecord | null;
  response?: PublicMcpResponse;
}) {
  return (
    <div className="trace-layout">
      <section className="panel call-list-panel">
        <PanelTitle title="外部 MCP 调用" subtitle="包含 Claude Code、其他 agent 和调试页触发的 public MCP 调用。" />
        <div className="call-list">
          {props.calls.length ? (
            props.calls.map((call, index) => (
              <button
                type="button"
                key={`${call.ts}-${index}`}
                className={props.selectedIndex === index ? "call-item active" : "call-item"}
                onClick={() => props.setSelectedIndex(index)}
              >
                <span className={`badge ${call.status}`}>{call.status}</span>
                <strong>{call.caller || "unknown"}</strong>
                <em>{call.question || call.tool}</em>
                <small>{formatDate(call.ts)}</small>
              </button>
            ))
          ) : (
            <div className="empty">暂无 MCP 调用记录。</div>
          )}
        </div>
      </section>
      <section className="panel call-detail-panel">
        <PanelTitle title="调用详情" subtitle={props.selected ? `${props.selected.tool} / ${formatDate(props.selected.ts)}` : "选择一条调用记录"} />
        {props.selected ? (
          <>
            <div className="summary-cards">
              <Metric label="caller" value={props.selected.caller || "-"} />
              <Metric label="status" value={props.selected.status || "-"} />
              <Metric label="rows" value={String(props.selected.row_count ?? "-")} />
              <Metric label="error" value={props.selected.error?.code || "-"} />
            </div>
            <div className="answer-box">
              <h3>{props.selected.question || props.selected.tool}</h3>
              <p>{String(props.response?.answer || "")}</p>
            </div>
            <SourceList tables={props.selected.source_tables || props.response?.result?.source_tables || []} />
            <pre className="sql-box">{props.response?.result?.sql || "无 SQL"}</pre>
            <TraceList trace={props.response?.trace ?? []} />
            <QueryResultTable result={props.response?.result ?? null} />
          </>
        ) : (
          <div className="empty">暂无详情。</div>
        )}
      </section>
    </div>
  );
}

function DebugPage(props: {
  apiKey: string;
  setApiKey: (value: string) => void;
  caller: string;
  setCaller: (value: string) => void;
  question: string;
  setQuestion: (value: string) => void;
  language: UiLanguage;
  setLanguage: (value: UiLanguage) => void;
  maxRows: string;
  setMaxRows: (value: string) => void;
  response: PublicMcpResponse | null;
  capabilities: Record<string, unknown> | null;
  sourceTables: string[];
  busy: BusyKey | null;
  onAsk: (event: FormEvent<HTMLFormElement>) => void;
  onCapabilities: () => void;
}) {
  return (
    <div className="debug-layout">
      <form className="panel debug-form" onSubmit={props.onAsk}>
        <PanelTitle title="调试 public MCP" subtitle="这里模拟外部 agent 调用 ask_agent，返回值会进入 Trace 日志。" />
        <Field label="Caller" value={props.caller} onChange={props.setCaller} />
        <Field label="MCP API Key" value={props.apiKey} onChange={props.setApiKey} type="password" placeholder="sk-1234" />
        <label className="field">
          <span>Question</span>
          <textarea value={props.question} onChange={(event) => props.setQuestion(event.target.value)} rows={5} />
        </label>
        <div className="form-grid compact-grid">
          <label className="field">
            <span>Language</span>
            <select value={props.language} onChange={(event) => props.setLanguage(event.target.value as UiLanguage)}>
              <option value="zh">中文</option>
              <option value="en">English</option>
            </select>
          </label>
          <Field label="Max Rows" value={props.maxRows} onChange={props.setMaxRows} />
        </div>
        <div className="button-row">
          <button type="submit" disabled={props.busy !== null || !props.question.trim()}>
            {props.busy === "ask" ? <Loader2 className="spin" size={16} /> : <Play size={16} />}
            调用 ask_agent
          </button>
          <button type="button" onClick={props.onCapabilities} disabled={props.busy !== null}>
            {props.busy === "capabilities" ? <Loader2 className="spin" size={16} /> : <FileText size={16} />}
            describe_capabilities
          </button>
        </div>
      </form>
      <section className="panel debug-result">
        <PanelTitle title="调试输出" subtitle={props.response?.caller ? `caller: ${props.response.caller}` : "尚未调用"} />
        <div className="summary-cards">
          <Metric label="status" value={props.response?.status || "idle"} />
          <Metric label="executed" value={String(Boolean(props.response?.executed))} />
          <Metric label="rows" value={String(props.response?.row_count ?? "-")} />
          <Metric label="requests" value={String(props.response?.token_usage.requests ?? 0)} />
        </div>
        <div className="answer-box">
          <h3>{props.response?.question || "等待调试问题"}</h3>
          <p>{props.response?.answer || "执行后显示 MCP 返回。"}</p>
          {props.response?.error ? <div className="error-detail"><strong>{props.response.error.code}</strong><span>{props.response.error.message}</span></div> : null}
        </div>
        <SourceList tables={props.sourceTables} />
        <pre className="sql-box">{props.response?.result?.sql || "尚未生成 SQL"}</pre>
        <TraceList trace={props.response?.trace ?? []} />
        <QueryResultTable result={props.response?.result ?? null} />
        <JsonPanel title="能力摘要" data={props.capabilities} empty="尚未调用 describe_capabilities。" />
      </section>
    </div>
  );
}

function NavButton(props: { active: boolean; icon: JSX.Element; label: string; onClick: () => void }) {
  return (
    <button type="button" className={props.active ? "nav-button active" : "nav-button"} onClick={props.onClick}>
      {props.icon}
      {props.label}
    </button>
  );
}

function PanelTitle({ title, subtitle }: { title: string; subtitle?: string }) {
  return (
    <div className="panel-header">
      <div>
        <h2>{title}</h2>
        {subtitle ? <span>{subtitle}</span> : null}
      </div>
    </div>
  );
}

function Field(props: { label: string; value: string; onChange: (value: string) => void; type?: string; placeholder?: string }) {
  return (
    <label className="field">
      <span>{props.label}</span>
      <input type={props.type || "text"} value={props.value} placeholder={props.placeholder} onChange={(event) => props.onChange(event.target.value)} />
    </label>
  );
}

function StatusLine({ label, ok, value }: { label: string; ok: boolean; value: string }) {
  return (
    <div className="status-line">
      {ok ? <CheckCircle2 size={14} /> : <AlertCircle size={14} />}
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function TestResult({ result }: { result?: ConfigTestResponse }) {
  if (!result) {
    return null;
  }
  return (
    <div className={result.ok ? "test-result ok" : "test-result error"}>
      <strong>{result.ok ? "OK" : "FAIL"}</strong>
      <span>{result.message}</span>
      {result.latency_ms !== null && result.latency_ms !== undefined ? <em>{result.latency_ms} ms</em> : null}
    </div>
  );
}

function ColumnList({ table }: { table: TableMetadata | null }) {
  if (!table) {
    return <div className="empty compact-empty">未选择表。</div>;
  }
  return (
    <div className="column-list">
      {table.columns.slice(0, 12).map((column) => (
        <span key={String(column.column_name)}>
          <strong>{String(column.column_name)}</strong>
          <em>{String(column.data_type || "")}</em>
        </span>
      ))}
    </div>
  );
}

function TraceList({ trace }: { trace: TraceStep[] }) {
  if (!trace.length) {
    return <div className="empty">暂无执行链路。</div>;
  }
  return (
    <div className="trace-list">
      {trace.map((step, index) => (
        <details key={`${step.name}-${index}`} open={index === trace.length - 1 || step.status === "error"}>
          <summary>
            <span className={`dot ${step.status}`} />
            <strong>{step.name}</strong>
            <em>{step.summary}</em>
          </summary>
          <pre>{JSON.stringify(step.detail, null, 2)}</pre>
        </details>
      ))}
    </div>
  );
}

function QueryResultTable({ result }: { result: QueryResult | null }) {
  if (!result || !result.columns.length) {
    return <div className="empty">暂无结构化结果。</div>;
  }
  return (
    <div className="table-wrap">
      <table>
        <thead>
          <tr>
            {result.columns.map((column) => <th key={column}>{column}</th>)}
          </tr>
        </thead>
        <tbody>
          {result.rows.map((row, index) => (
            <tr key={index}>
              {result.columns.map((column) => <td key={column}>{formatValue(row[column])}</td>)}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function SourceList({ tables }: { tables: string[] }) {
  return (
    <div className="source-list">
      {tables.length ? tables.map((table) => <span key={table}>{table}</span>) : <span>暂无来源表</span>}
    </div>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="metric">
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function JsonPanel({ title, data, empty }: { title: string; data: unknown; empty: string }) {
  return (
    <section className="json-section">
      <h3>{title}</h3>
      <pre className="json-box">{data ? JSON.stringify(data, null, 2) : empty}</pre>
    </section>
  );
}

function pageTitle(page: PageKey): string {
  if (page === "settings") {
    return "设置与数据源";
  }
  if (page === "traces") {
    return "MCP 调用 Trace";
  }
  return "调试接口";
}

function pageSubtitle(page: PageKey): string {
  if (page === "settings") {
    return "配置 LLM、数据库连接，并预览当前数据库表。";
  }
  if (page === "traces") {
    return "查看外部 agent 调用 public MCP 的输入、输出、SQL 和执行链路。";
  }
  return "手动调用 public MCP，验证输出格式和错误状态。";
}

function emptyConfigForm(): ConfigForm {
  return {
    app_timezone: "Asia/Shanghai",
    pg_max_rows: "200",
    pg_statement_timeout_ms: "5000",
    pg_schema_limit: "80",
    pg_schemas: "",
    agent_verbose_debug: false,
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
    pg_schemas: config.pg_schemas.join(","),
    agent_verbose_debug: config.agent_verbose_debug,
    llm_provider: config.llm.provider || "",
    llm_base_url: config.llm.base_url || "",
    llm_model: config.llm.model || "",
    llm_api_key: "",
    llm_timeout_seconds: String(config.llm.timeout_seconds),
    db_host: config.database.host || "",
    db_port: config.database.port ? String(config.database.port) : "",
    db_name: config.database.database || "",
    db_user: config.database.username || "",
    db_password: "",
    db_sslmode: config.database.sslmode || ""
  };
}

function formToPayload(form: ConfigForm): RuntimeConfigUpdate {
  return {
    app_timezone: form.app_timezone || undefined,
    pg_max_rows: toInt(form.pg_max_rows),
    pg_statement_timeout_ms: toInt(form.pg_statement_timeout_ms),
    pg_schema_limit: toInt(form.pg_schema_limit),
    pg_schemas: parseSchemaNames(form.pg_schemas),
    agent_verbose_debug: form.agent_verbose_debug,
    llm_provider: form.llm_provider || undefined,
    llm_base_url: form.llm_base_url || undefined,
    llm_model: form.llm_model || undefined,
    llm_api_key: form.llm_api_key || undefined,
    llm_timeout_seconds: toInt(form.llm_timeout_seconds),
    db_host: form.db_host || undefined,
    db_port: toInt(form.db_port),
    db_name: form.db_name || undefined,
    db_user: form.db_user || undefined,
    db_password: form.db_password || undefined,
    db_sslmode: form.db_sslmode || undefined
  };
}

function parseSchemaNames(value: string): string[] {
  return value.split(/[\s,]+/).map((item) => item.trim()).filter(Boolean);
}

function extractSchemaTables(schema: Record<string, unknown> | null | undefined): string[] {
  const tables = schema?.tables;
  if (!Array.isArray(tables)) {
    return [];
  }
  return tables
    .map((item) => {
      if (!item || typeof item !== "object") {
        return "";
      }
      const record = item as Record<string, unknown>;
      const table = String(record.table || "");
      const schemaName = String(record.schema || "");
      return table ? (schemaName ? `${schemaName}.${table}` : table) : "";
    })
    .filter(Boolean);
}

function tableKey(table: TableMetadata): string {
  return `${table.schema}.${table.table}`;
}

function toInt(value: string): number | undefined {
  const parsed = Number.parseInt(value, 10);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : undefined;
}

function formatValue(value: unknown): string {
  if (value === null || value === undefined) {
    return "";
  }
  if (typeof value === "object") {
    return JSON.stringify(value);
  }
  return String(value);
}

function formatError(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

function formatDate(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return date.toLocaleString();
}

export default App;
