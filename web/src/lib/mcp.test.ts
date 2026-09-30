import { describe, expect, it, vi } from "vitest";

import { FinanceMcpClient, parseTraceEnvelope, type McpAdapter } from "./mcp";

const TOOLS = [
  { name: "get_app_settings" },
  { name: "update_app_settings" },
  { name: "parse_budget_rules" },
  { name: "create_finance_session" },
  { name: "ask_finance_agent" },
  { name: "close_finance_session" },
  { name: "delete_chat_thread" },
  { name: "get_chat_thread" },
  { name: "list_chat_threads" },
  { name: "update_chat_thread" },
];

function fakeAdapter(result: unknown): McpAdapter {
  return {
    connect: vi.fn().mockResolvedValue(undefined),
    listTools: vi.fn().mockResolvedValue({ tools: TOOLS }),
    callTool: vi.fn().mockResolvedValue(result),
    terminateSession: vi.fn().mockResolvedValue(undefined),
    close: vi.fn().mockResolvedValue(undefined),
  };
}

describe("FinanceMcpClient", () => {
  it("validates live trace notifications and ignores another thread", async () => {
    const threadId = "8a68c223-7e5a-4adc-9f1a-9c18a8f87be0";
    const envelope = { version: 1, thread_id: threadId, turn_id: threadId,
      event: { sequence: 1, timestamp: "2026-09-30T08:00:00Z", operation_id: "model-1", stage: "model", state: "started", payload: {} } };
    expect(parseTraceEnvelope(JSON.stringify(envelope))).toEqual(envelope);
    expect(parseTraceEnvelope("invalid JSON")).toBeNull();
    for (const invalid of [{ sequence: -1 }, { stage: "unknown" }, { duration_ms: -1 }, { payload: [] }, { timestamp: "2026-09-30T08:00:00" }]) {
      expect(parseTraceEnvelope(JSON.stringify({ ...envelope, event: { ...envelope.event, ...invalid } }))).toBeNull();
    }
    const adapter = fakeAdapter({ structuredContent: { answer: "Done", status: "ok", steps: 1 } });
    vi.mocked(adapter.callTool).mockImplementation(async (_name, _args, options) => {
      expect(options?.timeout).toBe(600_000);
      options?.onprogress?.({ message: "broken" });
      options?.onprogress?.({ message: JSON.stringify({ ...envelope, thread_id: "4726647e-78ca-461b-b7a0-6653e8f6a58d" }) });
      options?.onprogress?.({ message: JSON.stringify(envelope) });
      return { structuredContent: { answer: "Done", status: "ok", steps: 1 } };
    });
    const progress = vi.fn();
    await new FinanceMcpClient(() => adapter).askFinanceAgent({ session_id: threadId, question: "Check" }, progress);
    expect(progress).toHaveBeenCalledExactlyOnceWith(envelope);
  });
  it("discovers the exact tools and returns a valid structured result", async () => {
    const adapter = fakeAdapter({
      structuredContent: {
        session_id: "session-1",
        as_of_date: "2026-08-15",
        context_mode: "auto",
        transaction_count: 4,
        budget_rules: [],
        compaction_turns: 15,
        max_agent_steps: 15,
        ledger_source: "demo",
      },
    });
    const client = new FinanceMcpClient(() => adapter);

    await expect(client.createFinanceSession({})).resolves.toMatchObject({
      session_id: "session-1",
      transaction_count: 4,
    });
    expect(adapter.connect).toHaveBeenCalledTimes(1);
    expect(adapter.listTools).toHaveBeenCalledTimes(1);
  });

  it("rejects a discovered tool set that does not match the server contract", async () => {
    const adapter = fakeAdapter({});
    vi.mocked(adapter.listTools).mockResolvedValue({ tools: TOOLS.slice(0, 3) });
    const client = new FinanceMcpClient(() => adapter);

    await expect(client.connect()).rejects.toThrow("Unexpected MCP tools");
  });

  it("surfaces MCP tool errors", async () => {
    const adapter = fakeAdapter({
      isError: true,
      content: [{ type: "text", text: "Invalid ledger" }],
    });
    const client = new FinanceMcpClient(() => adapter);

    await expect(client.parseBudgetRules({ rules_text: "rule" })).rejects.toThrow(
      "Invalid ledger",
    );
  });

  it("validates persisted thread list and detail results", async () => {
    const adapter = fakeAdapter({
      structuredContent: {
        threads: [{
          thread_id: "thread-1",
          title: "Review",
          created_at: "2026-09-30T08:00:00Z",
          updated_at: "2026-09-30T08:00:00Z",
          turn_count: 1,
          ledger_source: "demo",
        }],
        skipped_files: 0,
      },
    });
    const client = new FinanceMcpClient(() => adapter);

    await expect(client.listChatThreads()).resolves.toMatchObject({
      threads: [{ title: "Review" }],
      skipped_files: 0,
    });
  });

  it("rejects missing structured content", async () => {
    const client = new FinanceMcpClient(() => fakeAdapter({ content: [] }));

    await expect(client.closeFinanceSession({ session_id: "session-1" })).rejects.toThrow(
      "returned no structured content",
    );
  });

  it("rejects malformed required fields", async () => {
    const client = new FinanceMcpClient(() =>
      fakeAdapter({ structuredContent: { answer: "Done", status: "ok" } }),
    );

    await expect(
      client.askFinanceAgent({ session_id: "session-1", question: "How am I doing?" }),
    ).rejects.toThrow("returned invalid structured content");
  });

  it("adds restart guidance for an unknown tool", async () => {
    const client = new FinanceMcpClient(() =>
      fakeAdapter({
        isError: true,
        content: [{ type: "text", text: "Unknown tool: parse_budget_rules" }],
      }),
    );

    await expect(client.parseBudgetRules({ rules_text: "rule" })).rejects.toThrow(
      "Restart the MCP server",
    );
  });

  it("does not retry a failed call and reconnects only on the next explicit call", async () => {
    const failed = fakeAdapter({});
    vi.mocked(failed.callTool).mockRejectedValue(new Error("Error POSTing to endpoint:"));
    const recovered = fakeAdapter({
      structuredContent: { session_id: "session-1", closed: true },
    });
    const adapters = [failed, recovered];
    const client = new FinanceMcpClient(() => {
      const adapter = adapters.shift();
      if (!adapter) throw new Error("unexpected reconnect");
      return adapter;
    });

    await expect(client.closeFinanceSession({ session_id: "session-1" })).rejects.toThrow(
      "MCP server unavailable",
    );
    expect(failed.callTool).toHaveBeenCalledTimes(1);
    expect(recovered.callTool).not.toHaveBeenCalled();

    await expect(client.closeFinanceSession({ session_id: "session-1" })).resolves.toEqual({
      session_id: "session-1",
      closed: true,
    });
    expect(recovered.callTool).toHaveBeenCalledTimes(1);
  });
});

it("validates shared settings and sends partial updates", async () => {
  const settings = { version: 1, rules_text: "Save 20%", rules_draft: "Save 20%", budget_rules: [{ rule_id: "savings", source_text: "Save 20%" }], context_mode: "auto", compaction_turns: 15, max_agent_steps: 15 };
  const adapter = fakeAdapter({ structuredContent: settings });
  const client = new FinanceMcpClient(() => adapter);
  await expect(client.getAppSettings()).resolves.toEqual(settings);
  await client.updateAppSettings({ max_agent_steps: 25 });
  expect(adapter.callTool).toHaveBeenLastCalledWith("update_app_settings", { max_agent_steps: 25 }, undefined);
  vi.mocked(adapter.callTool).mockResolvedValue({ structuredContent: { ...settings, compaction_turns: 4 } });
  await expect(client.getAppSettings()).rejects.toThrow("invalid structured content");
});
