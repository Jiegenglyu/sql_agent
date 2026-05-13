import type {
  AgentResponse,
  ConfigTestResponse,
  HealthResponse,
  QueryResult,
  RuntimeConfigResponse,
  RuntimeConfigUpdate,
  SchemaMetadataResponse,
  SqlValidation,
  TraceStep,
  UiLanguage
} from "./types";

const API_BASE = import.meta.env.VITE_API_BASE_URL || "http://localhost:8000";
const API_PREFIX = normalizeApiPrefix(import.meta.env.VITE_API_PREFIX || "/api");

function normalizeApiPrefix(value: string): string {
  const clean = value.trim().replace(/\/+$/, "");
  if (!clean) {
    return "";
  }
  return clean.startsWith("/") ? clean : `/${clean}`;
}

function apiPath(path: string): string {
  return `${API_PREFIX}${path}`;
}

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    headers: {
      "Content-Type": "application/json",
      ...(options?.headers ?? {})
    },
    ...options
  });
  if (!response.ok) {
    const detail = await response.text();
    throw new Error(detail || response.statusText);
  }
  return response.json() as Promise<T>;
}

export function getHealth(): Promise<HealthResponse> {
  return request<HealthResponse>("/health");
}

export function getRuntimeConfig(): Promise<RuntimeConfigResponse> {
  return request<RuntimeConfigResponse>(apiPath("/config"));
}

export function updateRuntimeConfig(config: RuntimeConfigUpdate): Promise<RuntimeConfigResponse> {
  return request<RuntimeConfigResponse>(apiPath("/config"), {
    method: "PUT",
    body: JSON.stringify(config)
  });
}

export function testDatabaseConfig(config: RuntimeConfigUpdate): Promise<ConfigTestResponse> {
  return request<ConfigTestResponse>(apiPath("/config/test/database"), {
    method: "POST",
    body: JSON.stringify(config)
  });
}

export function testLlmConfig(config: RuntimeConfigUpdate): Promise<ConfigTestResponse> {
  return request<ConfigTestResponse>(apiPath("/config/test/llm"), {
    method: "POST",
    body: JSON.stringify(config)
  });
}

export function queryAgent(question: string, language: UiLanguage): Promise<AgentResponse> {
  return request<AgentResponse>(apiPath("/agent/query"), {
    method: "POST",
    body: JSON.stringify({ question, execute: true, language })
  });
}

export interface AgentStreamHandlers {
  onTrace?: (step: TraceStep) => void;
  onFinal?: (response: AgentResponse) => void;
  onError?: (message: string) => void;
}

export async function queryAgentStream(
  question: string,
  language: UiLanguage,
  handlers: AgentStreamHandlers = {}
): Promise<AgentResponse> {
  const response = await fetch(`${API_BASE}${apiPath("/agent/query/stream")}`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Accept: "text/event-stream"
    },
    body: JSON.stringify({ question, execute: true, language })
  });

  if (!response.ok) {
    const detail = await response.text();
    throw new Error(detail || response.statusText);
  }
  if (!response.body) {
    const fallback = await queryAgent(question, language);
    handlers.onFinal?.(fallback);
    return fallback;
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let finalResponse: AgentResponse | null = null;
  let streamError: string | null = null;

  function handleBlock(rawBlock: string) {
    const block = rawBlock.trim();
    if (!block) {
      return;
    }

    let eventType = "message";
    const dataLines: string[] = [];
    block.split("\n").forEach((line) => {
      if (line.startsWith("event:")) {
        eventType = line.slice("event:".length).trim();
      } else if (line.startsWith("data:")) {
        dataLines.push(line.slice("data:".length).trimStart());
      }
    });

    const data = dataLines.length > 0 ? JSON.parse(dataLines.join("\n")) : {};
    if (eventType === "trace" && data.step) {
      handlers.onTrace?.(data.step as TraceStep);
    } else if (eventType === "final" && data.response) {
      finalResponse = data.response as AgentResponse;
      handlers.onFinal?.(finalResponse);
    } else if (eventType === "error") {
      streamError = String(data.message || "Agent stream failed.");
      handlers.onError?.(streamError);
    }
  }

  while (true) {
    const { done, value } = await reader.read();
    if (value) {
      buffer += decoder.decode(value, { stream: !done });
      let separatorIndex = buffer.indexOf("\n\n");
      while (separatorIndex >= 0) {
        handleBlock(buffer.slice(0, separatorIndex));
        buffer = buffer.slice(separatorIndex + 2);
        separatorIndex = buffer.indexOf("\n\n");
      }
    }
    if (done) {
      break;
    }
  }

  buffer += decoder.decode();
  if (buffer.trim()) {
    handleBlock(buffer);
  }

  if (streamError) {
    throw new Error(streamError);
  }
  if (!finalResponse) {
    throw new Error("Agent stream ended without a final response.");
  }
  return finalResponse;
}

export function getSchemaMetadata(limit?: number, schemas?: string[]): Promise<SchemaMetadataResponse> {
  const params = new URLSearchParams();
  if (limit !== undefined) {
    params.set("limit", String(limit));
  }
  if (schemas !== undefined) {
    if (schemas.length === 0) {
      params.append("schema", "");
    } else {
      schemas.forEach((schema) => params.append("schema", schema));
    }
  }
  const suffix = params.toString() ? `?${params.toString()}` : "";
  return request<SchemaMetadataResponse>(apiPath(`/schema/metadata${suffix}`));
}

export function previewTable(schema: string, table: string, limit = 10): Promise<QueryResult> {
  const params = new URLSearchParams({
    schema,
    table,
    limit: String(limit)
  });
  return request<QueryResult>(apiPath(`/schema/table-preview?${params.toString()}`));
}

export function validateSql(sql: string): Promise<SqlValidation> {
  return request<SqlValidation>(apiPath("/sql/validate"), {
    method: "POST",
    body: JSON.stringify({ sql })
  });
}

export function executeSql(sql: string): Promise<QueryResult> {
  return request<QueryResult>(apiPath("/sql/execute"), {
    method: "POST",
    body: JSON.stringify({ sql })
  });
}
