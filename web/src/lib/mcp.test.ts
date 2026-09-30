import { describe, expect, it, vi } from "vitest";

import { FinanceMcpClient, type McpAdapter } from "./mcp";

const TOOLS = [
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
  it("discovers the exact tools and returns a valid structured result", async () => {
    const adapter = fakeAdapter({
      structuredContent: {
        session_id: "session-1",
        as_of_date: "2026-08-15",
        context_mode: "auto",
        transaction_count: 4,
        budget_rules: [],
        compaction_turns: 15,
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
