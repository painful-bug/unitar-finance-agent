import { Client, StreamableHTTPClientTransport } from "@modelcontextprotocol/client";

import type {
  AppSettings,
  UpdateAppSettingsInput,
  AgentResult,
  AskFinanceAgentInput,
  BudgetRulePreview,
  ChatThreadDetail,
  ChatThreadList,
  CloseFinanceSessionInput,
  CloseResult,
  CreateFinanceSessionInput,
  DeleteChatThreadResult,
  ParseBudgetRulesInput,
  SessionInfo,
  UpdateChatThreadInput,
  ExecutionTraceEvent,
  TraceEnvelope,
} from "../types";

const EXPECTED_TOOLS = [
  "ask_finance_agent",
  "close_finance_session",
  "create_finance_session",
  "delete_chat_thread",
  "get_app_settings",
  "get_chat_thread",
  "list_chat_threads",
  "parse_budget_rules",
  "update_app_settings",
  "update_chat_thread",
] as const;

type ToolResult = {
  isError?: boolean;
  content?: Array<{ type?: string; text?: string }>;
  structuredContent?: unknown;
};

export type McpAdapter = {
  connect: () => Promise<void>;
  listTools: () => Promise<{ tools: Array<{ name: string }> }>;
  callTool: (name: string, arguments_: Record<string, unknown>, options?: { onprogress?: (progress: { message?: string }) => void; timeout?: number }) => Promise<ToolResult>;
  terminateSession: () => Promise<void>;
  close: () => Promise<void>;
};

type AdapterFactory = () => McpAdapter;
type ObjectGuard<T> = (value: unknown) => value is T;

function createSdkAdapter(): McpAdapter {
  const client = new Client({ name: "finance-agent-web", version: "0.1.0" });
  const transport = new StreamableHTTPClientTransport(new URL("/mcp", window.location.origin));

  return {
    connect: () => client.connect(transport, { timeout: 10_000 }),
    listTools: () => client.listTools(),
    callTool: (name, arguments_, options) => client.callTool({ name, arguments: arguments_ }, options),
    terminateSession: () => transport.terminateSession(),
    close: () => client.close(),
  };
}

function isObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

export function isExecutionTraceEvent(value: unknown): value is ExecutionTraceEvent {
  if (!isObject(value)) return false;
  return Number.isSafeInteger(value.sequence) && Number(value.sequence) > 0 &&
    typeof value.timestamp === "string" && Number.isFinite(Date.parse(value.timestamp)) &&
    /(?:Z|\+00:00)$/.test(value.timestamp) &&
    typeof value.operation_id === "string" && value.operation_id.length > 0 &&
    ["prompt", "context", "model", "tool", "outcome"].includes(String(value.stage)) &&
    ["started", "completed", "failed", "warning"].includes(String(value.state)) &&
    (value.step == null || (Number.isSafeInteger(value.step) && Number(value.step) > 0)) &&
    (value.tool_call_id == null || typeof value.tool_call_id === "string") &&
    (value.duration_ms == null || (typeof value.duration_ms === "number" && Number.isFinite(value.duration_ms) && value.duration_ms >= 0)) &&
    isObject(value.payload);
}

export function parseTraceEnvelope(message: string | undefined): TraceEnvelope | null {
  if (!message) return null;
  try {
    const value: unknown = JSON.parse(message);
    return isObject(value) && value.version === 1 &&
      typeof value.thread_id === "string" && typeof value.turn_id === "string" &&
      /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(value.thread_id) &&
      /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(value.turn_id) &&
      isExecutionTraceEvent(value.event) ? value as unknown as TraceEnvelope : null;
  } catch { return null; }
}

function textContent(result: ToolResult): string {
  return (result.content ?? [])
    .filter((item) => item.type === "text" && typeof item.text === "string")
    .map((item) => item.text)
    .join(" ")
    .trim();
}

function clientError(error: unknown): Error {
  const message = error instanceof Error ? error.message : String(error);
  if (message.startsWith("Unknown tool:")) {
    return new Error(
      `${message}. The MCP server is running older code. Restart the MCP server with ` +
        "`uv run --env-file .env finance-mcp`, then try again.",
    );
  }
  if (/fetch|network|ECONNREFUSED|POSTing to endpoint/i.test(message)) {
    return new Error("MCP server unavailable.");
  }
  return new Error(message || "MCP server unavailable.");
}

function assertExpectedTools(tools: Array<{ name: string }>): void {
  const actual = tools.map(({ name }) => name).sort();
  if (actual.length !== EXPECTED_TOOLS.length || actual.some((name, index) => name !== EXPECTED_TOOLS[index])) {
    throw new Error(
      `Unexpected MCP tools: ${actual.join(", ") || "none"}. Restart the MCP server with ` +
        "`uv run --env-file .env finance-mcp`, then try again.",
    );
  }
}

function isAppSettings(value: unknown): value is AppSettings {
  return isObject(value) && value.version === 1 && typeof value.rules_text === "string" &&
    typeof value.rules_draft === "string" && Array.isArray(value.budget_rules) && value.budget_rules.length > 0 &&
    ["auto", "jev", "summary"].includes(String(value.context_mode)) &&
    Number.isInteger(value.compaction_turns) && Number(value.compaction_turns) >= 5 && Number(value.compaction_turns) <= 100 &&
    Number.isInteger(value.max_agent_steps) && Number(value.max_agent_steps) >= 1 && Number(value.max_agent_steps) <= 100;
}

function isBudgetRulePreview(value: unknown): value is BudgetRulePreview {
  if (!isObject(value)) return false;
  return Array.isArray(value.rules);
}

function isSessionInfo(value: unknown): value is SessionInfo {
  if (!isObject(value)) return false;
  return (
    typeof value.session_id === "string" &&
    typeof value.as_of_date === "string" &&
    ["auto", "jev", "summary"].includes(String(value.context_mode)) &&
    typeof value.transaction_count === "number" &&
    Array.isArray(value.budget_rules) &&
    typeof value.compaction_turns === "number" &&
    Number.isInteger(value.compaction_turns) &&
    value.compaction_turns >= 5 &&
    value.compaction_turns <= 100 &&
    typeof value.max_agent_steps === "number" &&
    Number.isInteger(value.max_agent_steps) &&
    value.max_agent_steps >= 1 &&
    value.max_agent_steps <= 100 &&
    ["demo", "upload"].includes(String(value.ledger_source))
  );
}

function isAgentResult(value: unknown): value is AgentResult {
  if (!isObject(value)) return false;
  return (
    typeof value.answer === "string" &&
    ["ok", "max_steps", "error", "context_error"].includes(String(value.status)) &&
    typeof value.steps === "number"
  );
}

function isCloseResult(value: unknown): value is CloseResult {
  if (!isObject(value)) return false;
  return typeof value.session_id === "string" && typeof value.closed === "boolean";
}

function isThreadSummary(value: unknown): boolean {
  return (
    isObject(value) &&
    typeof value.thread_id === "string" &&
    typeof value.title === "string" &&
    typeof value.created_at === "string" &&
    typeof value.updated_at === "string" &&
    typeof value.turn_count === "number" &&
    ["demo", "upload"].includes(String(value.ledger_source))
  );
}

function isChatThreadList(value: unknown): value is ChatThreadList {
  return (
    isObject(value) &&
    Array.isArray(value.threads) &&
    value.threads.every(isThreadSummary) &&
    typeof value.skipped_files === "number"
  );
}

function isChatThreadDetail(value: unknown): value is ChatThreadDetail {
  return (
    isObject(value) &&
    isThreadSummary(value.summary) &&
    typeof value.as_of_date === "string" &&
    ["auto", "jev", "summary"].includes(String(value.context_mode)) &&
    typeof value.transaction_count === "number" &&
    Array.isArray(value.budget_rules) &&
    typeof value.compaction_turns === "number" &&
    typeof value.max_agent_steps === "number" &&
    Array.isArray(value.turns) && value.turns.every((turn) => isObject(turn) &&
      typeof turn.turn_id === "string" && typeof turn.question === "string" &&
      typeof turn.created_at === "string" && ["pending", "complete", "interrupted"].includes(String(turn.state)) &&
      (turn.execution_trace_version == null || turn.execution_trace_version === 1) &&
      (turn.execution_trace === undefined || (Array.isArray(turn.execution_trace) && turn.execution_trace.every(isExecutionTraceEvent))))
  );
}

function isDeleteChatThreadResult(value: unknown): value is DeleteChatThreadResult {
  return (
    isObject(value) &&
    typeof value.thread_id === "string" &&
    typeof value.deleted === "boolean"
  );
}

export class FinanceMcpClient {
  private adapter: McpAdapter | null = null;
  private connecting: Promise<void> | null = null;

  constructor(private readonly adapterFactory: AdapterFactory = createSdkAdapter) {}

  async connect(): Promise<void> {
    if (this.adapter) return;
    if (this.connecting) return this.connecting;

    const adapter = this.adapterFactory();
    this.connecting = (async () => {
      try {
        await adapter.connect();
        const { tools } = await adapter.listTools();
        assertExpectedTools(tools);
        this.adapter = adapter;
      } catch (error) {
        await adapter.close().catch(() => undefined);
        throw clientError(error);
      }
    })();

    try {
      await this.connecting;
    } finally {
      this.connecting = null;
    }
  }

  getAppSettings(): Promise<AppSettings> {
    return this.call("get_app_settings", {}, isAppSettings);
  }

  updateAppSettings(input: UpdateAppSettingsInput): Promise<AppSettings> {
    return this.call("update_app_settings", input, isAppSettings);
  }

  parseBudgetRules(input: ParseBudgetRulesInput): Promise<BudgetRulePreview> {
    return this.call("parse_budget_rules", input, isBudgetRulePreview);
  }

  createFinanceSession(input: CreateFinanceSessionInput): Promise<SessionInfo> {
    return this.call("create_finance_session", input, isSessionInfo);
  }

  askFinanceAgent(input: AskFinanceAgentInput, onProgress?: (envelope: TraceEnvelope) => void): Promise<AgentResult> {
    return this.call("ask_finance_agent", input, isAgentResult, {
      timeout: 600_000,
      onprogress: ({ message }) => {
        const envelope = parseTraceEnvelope(message);
        if (envelope?.thread_id === input.session_id) onProgress?.(envelope);
      },
    });
  }

  closeFinanceSession(input: CloseFinanceSessionInput): Promise<CloseResult> {
    return this.call("close_finance_session", input, isCloseResult);
  }

  listChatThreads(): Promise<ChatThreadList> {
    return this.call("list_chat_threads", {}, isChatThreadList);
  }

  getChatThread(threadId: string): Promise<ChatThreadDetail> {
    return this.call("get_chat_thread", { thread_id: threadId }, isChatThreadDetail);
  }

  updateChatThread(input: UpdateChatThreadInput): Promise<ChatThreadDetail> {
    return this.call("update_chat_thread", input, isChatThreadDetail);
  }

  deleteChatThread(threadId: string): Promise<DeleteChatThreadResult> {
    return this.call(
      "delete_chat_thread",
      { thread_id: threadId },
      isDeleteChatThreadResult,
    );
  }

  async close(): Promise<void> {
    await this.connecting?.catch(() => undefined);
    const adapter = this.adapter;
    this.adapter = null;
    if (!adapter) return;
    await adapter.terminateSession().catch(() => undefined);
    await adapter.close().catch(() => undefined);
  }

  private async call<T>(
    name: string,
    arguments_: object,
    guard: ObjectGuard<T>,
    options?: Parameters<McpAdapter["callTool"]>[2],
  ): Promise<T> {
    await this.connect();
    const adapter = this.adapter;
    if (!adapter) throw new Error("MCP server unavailable.");

    let result: ToolResult;
    try {
      result = await adapter.callTool(name, arguments_ as Record<string, unknown>, options);
    } catch (error) {
      await this.invalidate();
      throw clientError(error);
    }

    const detail = textContent(result);
    if (result.isError) throw clientError(detail || `MCP tool ${name} failed`);
    if (!isObject(result.structuredContent)) {
      throw new Error(`MCP tool ${name} returned no structured content.`);
    }
    if (!guard(result.structuredContent)) {
      throw new Error(`MCP tool ${name} returned invalid structured content.`);
    }
    return result.structuredContent;
  }

  private async invalidate(): Promise<void> {
    const adapter = this.adapter;
    this.adapter = null;
    await adapter?.close().catch(() => undefined);
  }
}
