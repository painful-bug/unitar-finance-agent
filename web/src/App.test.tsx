import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import App from "./App";
import type { AppSettings, UpdateAppSettingsInput, AgentResult, AskFinanceAgentInput, ChatThreadDetail, ChatThreadSummary, SessionInfo, TraceEnvelope } from "./types";


const THREAD_ID = "8a68c223-7e5a-4adc-9f1a-9c18a8f87be0";
const SECOND_ID = "4726647e-78ca-461b-b7a0-6653e8f6a58d";
const result: AgentResult = {
  answer: "**Savings are RM200.**\n\n| Month | Rate |\n|---|---|\n| Aug | 20% |",
  status: "ok",
  steps: 1,
  trace: [{ step: 1, tool: "calculate_savings_rate", arguments: { month: "2026-08" }, result: { month: "2026-08", income: "1000.00", expenses: "800.00", savings: "200.00", rate: "20.00" } }],
  context: { strategy: "none", before_tokens: 20, after_tokens: 20, before_messages: [], after_messages: [] },
};

function summary(threadId = THREAD_ID, title = "August review"): ChatThreadSummary {
  return {
    thread_id: threadId,
    title,
    created_at: "2026-09-30T08:00:00Z",
    updated_at: "2026-09-30T08:00:00Z",
    turn_count: 1,
    ledger_source: "demo",
  };
}

function detail(threadId = THREAD_ID, title = "August review"): ChatThreadDetail {
  return {
    summary: summary(threadId, title),
    as_of_date: "2026-08-15",
    context_mode: "auto",
    transaction_count: 4,
    budget_rules: [],
    compaction_turns: 15,
    max_agent_steps: 15,
    turns: [{ turn_id: SECOND_ID, created_at: "2026-09-30T08:00:00Z", question: "How much did I save?", state: "complete", result }],
  };
}

function mockClient(saved: ChatThreadDetail[] = []) {
  const records = new Map(saved.map((thread) => [thread.summary.thread_id, thread]));
  const created: SessionInfo = {
    session_id: THREAD_ID,
    as_of_date: "2026-08-15",
    context_mode: "auto",
    transaction_count: 4,
    budget_rules: [],
    compaction_turns: 15,
    max_agent_steps: 15,
    ledger_source: "demo",
  };
  let settings: AppSettings = { version: 1, rules_text: "Save 20%", rules_draft: "Save 20%", budget_rules: [{ rule_id: "savings", source_text: "Save 20%", supported: true }], context_mode: "auto", compaction_turns: 15, max_agent_steps: 15 };
  return {
    getAppSettings: vi.fn().mockImplementation(async () => settings),
    updateAppSettings: vi.fn().mockImplementation(async (input: UpdateAppSettingsInput) => { settings = { ...settings, ...input }; return settings; }),
    closeFinanceSession: vi.fn().mockResolvedValue({ closed: true }),
    connect: vi.fn().mockResolvedValue(undefined),
    close: vi.fn().mockResolvedValue(undefined),
    listChatThreads: vi.fn().mockImplementation(async () => ({ threads: [...records.values()].map((thread) => thread.summary), skipped_files: 0 })),
    getChatThread: vi.fn().mockImplementation(async (threadId: string) => {
      const thread = records.get(threadId);
      if (!thread) throw new Error("Unknown chat thread.");
      return thread;
    }),
    createFinanceSession: vi.fn().mockResolvedValue(created),
    askFinanceAgent: vi.fn<(input: AskFinanceAgentInput, onProgress?: (envelope: TraceEnvelope) => void) => Promise<AgentResult>>().mockImplementation(async ({ session_id, question }) => {
      const next = detail(session_id, question.length > 48 ? `${question.slice(0, 47)}…` : question);
      next.turns[0].question = question;
      records.set(session_id, next);
      return result;
    }),
    updateChatThread: vi.fn().mockImplementation(async ({ thread_id, title, context_mode, compaction_turns, max_agent_steps }) => {
      const current = records.get(thread_id) ?? detail(thread_id);
      const next = {
        ...current,
        summary: { ...current.summary, title: title ?? current.summary.title },
        context_mode: context_mode ?? current.context_mode,
        compaction_turns: compaction_turns ?? current.compaction_turns,
        max_agent_steps: max_agent_steps ?? current.max_agent_steps,
      };
      records.set(thread_id, next);
      return next;
    }),
    deleteChatThread: vi.fn().mockImplementation(async (threadId: string) => ({ thread_id: threadId, deleted: records.delete(threadId) })),
    parseBudgetRules: vi.fn().mockResolvedValue({ rules: [] }),
  };
}

beforeEach(() => {
  window.history.replaceState({}, "", "/");
  localStorage.clear();
});

afterEach(cleanup);

describe("persistent chat shell", () => {
  it("lets Compact after turns be cleared before entering a new value", async () => {
    window.history.replaceState({}, "", `/chat/${THREAD_ID}`);
    const client = mockClient([detail()]);
    render(<App client={client} />);
    await screen.findByRole("heading", { name: "August review" });
    fireEvent.click(screen.getAllByRole("button", { name: "Settings" })[1]);
    const input = screen.getByLabelText("Compact after turns");
    fireEvent.change(input, { target: { value: "" } });
    expect(input).toHaveValue(null);
    fireEvent.change(input, { target: { value: "5" } });
    fireEvent.blur(input);
    await waitFor(() => expect(client.updateAppSettings).toHaveBeenCalledWith({ compaction_turns: 5 }));
  });

  it("opens a prompt's trace, preserves selection, and shares the inspector with Context", async () => {
    window.history.replaceState({}, "", `/chat/${THREAD_ID}`);
    render(<App client={mockClient([detail()])} />);
    await screen.findByRole("heading", { name: "August review" });
    fireEvent.click(screen.getByRole("button", { name: "View trace" }));
    expect(screen.getByLabelText("Prompt")).toHaveValue(SECOND_ID);
    fireEvent.click(screen.getByRole("button", { name: "Close trace" }));
    fireEvent.click(screen.getByRole("button", { name: "Trace" }));
    expect(screen.getByLabelText("Prompt")).toHaveValue(SECOND_ID);
    fireEvent.click(screen.getByRole("button", { name: "Context" }));
    expect(screen.getByRole("button", { name: "Trace" })).toHaveAttribute("aria-pressed", "false");
    fireEvent.click(screen.getByRole("button", { name: "Trace" }));
    expect(screen.getByRole("button", { name: "Context" })).toHaveAttribute("aria-pressed", "false");
    fireEvent.click(screen.getByRole("button", { name: "New chat" }));
    fireEvent.click(screen.getByRole("button", { name: "Trace" }));
    expect(screen.getByLabelText("Prompt")).toHaveValue("");
  });

  it("captures milestones while closed, deduplicates events, and reconciles on completion", async () => {
    window.history.replaceState({}, "", `/chat/${THREAD_ID}`);
    const client = mockClient([detail()]);
    let progress!: (envelope: TraceEnvelope) => void;
    let finish!: (value: AgentResult) => void;
    client.askFinanceAgent.mockImplementation((_input, callback) => { progress = callback!; return new Promise((resolve) => { finish = resolve; }); });
    const { container } = render(<App client={client} />);
    await screen.findByRole("heading", { name: "August review" });
    fireEvent.change(screen.getByLabelText("Ask about your spending, budget, or savings"), { target: { value: "Same new prompt" } });
    fireEvent.click(screen.getByRole("button", { name: "Send message" }));
    await waitFor(() => expect(client.askFinanceAgent).toHaveBeenCalledOnce());
    const envelope: TraceEnvelope = { version: 1, thread_id: THREAD_ID, turn_id: THREAD_ID,
      event: { sequence: 1, timestamp: "2026-09-30T08:00:00Z", operation_id: "prompt", stage: "prompt", state: "completed", payload: { question: "Same new prompt" } } };
    act(() => { progress(envelope); progress(envelope); progress({ ...envelope, event: { ...envelope.event, sequence: 2, operation_id: "model-1", stage: "model", state: "started", payload: {} } }); });
    fireEvent.click(screen.getByRole("button", { name: "Trace" }));
    expect(screen.getByRole("heading", { name: "Model request" })).toBeInTheDocument();
    expect(container.querySelectorAll(".trace-stage.is-prompt")).toHaveLength(1);
    fireEvent.change(screen.getByLabelText("Prompt"), { target: { value: SECOND_ID } });
    act(() => progress({ ...envelope, event: { ...envelope.event, sequence: 3, operation_id: "model-1", stage: "model", state: "completed", payload: { content: "Live new answer" } } }));
    expect(screen.getByLabelText("Prompt")).toHaveValue(SECOND_ID);
    expect(screen.queryByText("Live new answer")).not.toBeInTheDocument();
    client.getChatThread.mockResolvedValue(detail());
    await act(async () => { finish(result); });
    expect(screen.getByRole("button", { name: "Send message" })).toBeDisabled(); // Empty composer, request finished.
    expect(client.getChatThread).toHaveBeenCalledTimes(2);
  });

  it("keeps the compaction indicator after the pending turn arrives", async () => {
    window.history.replaceState({}, "", `/chat/${THREAD_ID}`);
    const thread = detail();
    thread.turns = Array.from({ length: 4 }, (_, index) => ({ ...thread.turns[0], turn_id: `turn-${index}`, question: `Question ${index + 1}` }));
    const client = mockClient([thread]);
    await client.updateAppSettings({ compaction_turns: 5 });
    let progress!: (envelope: TraceEnvelope) => void;
    client.askFinanceAgent.mockImplementation((_input, callback) => {
      progress = callback!;
      return new Promise(() => undefined);
    });
    render(<App client={client} />);
    await screen.findByRole("heading", { name: "August review" });
    fireEvent.change(screen.getByLabelText("Ask about your spending, budget, or savings"), { target: { value: "Compact these turns" } });
    fireEvent.click(screen.getByRole("button", { name: "Send message" }));
    await waitFor(() => expect(client.askFinanceAgent).toHaveBeenCalledOnce());

    act(() => progress({ version: 1, thread_id: THREAD_ID, turn_id: SECOND_ID, event: {
      sequence: 1, timestamp: "2026-09-30T08:00:00Z", operation_id: "prompt", stage: "prompt", state: "completed", payload: { question: "Compact these turns" },
    } }));
    expect(screen.getByRole("region", { name: "Conversation" })).toHaveTextContent("Compacting context…");
    expect(screen.getByRole("region", { name: "Conversation" })).not.toHaveTextContent("Thinking…");
  });

  it("renders a full-screen new-chat state and saved history", async () => {
    const client = mockClient([detail()]);
    render(<App client={client} />);

    expect(await screen.findByRole("heading", { name: "How can I help with your finances?" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "August review" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "New chat" })).toBeInTheDocument();
  });

  it("creates a thread on first submit, routes to it, and renders Markdown plus readable tools", async () => {
    const client = mockClient();
    render(<App client={client} />);

    await screen.findByRole("heading", { name: "How can I help with your finances?" });
    fireEvent.change(screen.getByLabelText("Ask about your spending, budget, or savings"), { target: { value: "How much did I save?" } });
    fireEvent.submit(screen.getByRole("button", { name: "Send message" }).closest("form")!);

    expect(await screen.findByText("Calculated savings rate")).toBeInTheDocument();
    expect(screen.getByText("Savings are RM200.")).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: "Month" })).toBeInTheDocument();
    expect(screen.getByText("Technical details")).toBeInTheDocument();
    expect(window.location.pathname).toBe(`/chat/${THREAD_ID}`);
    expect(client.createFinanceSession).toHaveBeenCalledTimes(1);
  });

  it("restores the routed conversation on refresh without creating a new session", async () => {
    window.history.replaceState({}, "", `/chat/${THREAD_ID}`);
    const client = mockClient([detail()]);
    render(<App client={client} />);

    expect(await screen.findByLabelText("assistant message")).toHaveTextContent("Savings are RM200.");
    expect(screen.getByRole("heading", { name: "August review" })).toBeInTheDocument();
    expect(client.getChatThread).toHaveBeenCalledWith(THREAD_ID);
    expect(client.createFinanceSession).not.toHaveBeenCalled();
  });

  it("renames a saved chat inline", async () => {
    window.history.replaceState({}, "", `/chat/${THREAD_ID}`);
    const client = mockClient([detail()]);
    render(<App client={client} />);
    await screen.findByRole("heading", { name: "August review" });

    fireEvent.click(screen.getByLabelText("Actions for August review"));
    fireEvent.click(screen.getByRole("button", { name: "Rename" }));
    const input = screen.getByLabelText("Rename August review");
    fireEvent.change(input, { target: { value: "Monthly plan" } });
    fireEvent.keyDown(input, { key: "Enter" });

    await waitFor(() => expect(client.updateChatThread).toHaveBeenCalledWith({ thread_id: THREAD_ID, title: "Monthly plan" }));
  });

  it("shows full-page settings and updates shared configuration in an existing chat", async () => {
    window.history.replaceState({}, "", `/chat/${THREAD_ID}`);
    const client = mockClient([detail()]);
    render(<App client={client} />);
    await screen.findByRole("heading", { name: "August review" });
    fireEvent.click(screen.getAllByRole("button", { name: "Settings" })[0]);

    expect(await screen.findByRole("heading", { name: "Make it work your way." })).toBeInTheDocument();
    expect(window.location.pathname).toBe("/settings");
    expect(screen.queryByRole("dialog", { name: "Chat settings" })).toBeNull();
    fireEvent.change(screen.getByLabelText("Strategy"), { target: { value: "summary" } });
    await waitFor(() => expect(client.updateAppSettings).toHaveBeenCalledWith({ context_mode: "summary" }));
    fireEvent.change(screen.getByLabelText("Max agent steps"), { target: { value: "25" } });
    fireEvent.blur(screen.getByLabelText("Max agent steps"));
    await waitFor(() => expect(client.updateAppSettings).toHaveBeenCalledWith({ max_agent_steps: 25 }));
  });

  it("keeps raw HTML inert in restored Markdown", async () => {
    const unsafe = detail();
    unsafe.turns[0].result = { ...result, answer: "<img src=x onerror=alert(1)> **safe**" };
    window.history.replaceState({}, "", `/chat/${THREAD_ID}`);
    const { container } = render(<App client={mockClient([unsafe])} />);

    expect(await screen.findByText("safe")).toBeInTheDocument();
    expect(container.querySelector("img")).toBeNull();
  });

  it("keeps browser history on the active chat while a request is in flight", async () => {
    window.history.replaceState({}, "", `/chat/${THREAD_ID}`);
    const client = mockClient([detail(), detail(SECOND_ID, "Other chat")]);
    let finish!: (value: AgentResult) => void;
    client.askFinanceAgent.mockImplementation(() => new Promise((resolve) => { finish = resolve; }));
    render(<App client={client} />);

    await screen.findByRole("heading", { name: "August review" });
    fireEvent.change(screen.getByLabelText("Ask about your spending, budget, or savings"), { target: { value: "Stay here" } });
    fireEvent.submit(screen.getByRole("button", { name: "Send message" }).closest("form")!);
    await waitFor(() => expect(client.askFinanceAgent).toHaveBeenCalledTimes(1));

    window.history.pushState({}, "", `/chat/${SECOND_ID}`);
    window.dispatchEvent(new PopStateEvent("popstate"));
    expect(window.location.pathname).toBe(`/chat/${THREAD_ID}`);
    expect(client.getChatThread).not.toHaveBeenCalledWith(SECOND_ID);

    await act(async () => { finish(result); });
  });
});

function csvFile(name: string, text = "date,kind,category,amount\n2026-09-01,income,salary,2000") {
  const file = new File([text], name, { type: "text/csv" });
  Object.defineProperty(file, "arrayBuffer", { value: async () => new TextEncoder().encode(text).buffer });
  return file;
}

describe("shared settings and chat ledgers", () => {
  it("validates uploads in the chat pane, reuses the draft, and resets new chats to bundled data", async () => {
    const client = mockClient();
    client.createFinanceSession.mockResolvedValueOnce({ session_id: SECOND_ID, as_of_date: "2026-09-01", context_mode: "auto", transaction_count: 1, budget_rules: [], compaction_turns: 15, max_agent_steps: 15, ledger_source: "upload", upload_name: "income.csv" });
    render(<App client={client} />);
    await screen.findByText("Agent service connected");
    expect(screen.getByRole("button", { name: "Choose CSV" })).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Ledger CSV"), { target: { files: [csvFile("income.csv")] } });
    expect(await screen.findByRole("heading", { name: "income.csv" })).toBeInTheDocument();
    expect(client.createFinanceSession).toHaveBeenCalledWith({ csv_text: expect.stringContaining("2000"), upload_name: "income.csv" });
    fireEvent.change(screen.getByLabelText("Ask about your spending, budget, or savings"), { target: { value: "Use my CSV" } });
    fireEvent.click(screen.getByRole("button", { name: "Send message" }));
    await screen.findByText("Calculated savings rate");
    expect(client.createFinanceSession).toHaveBeenCalledTimes(1);
    expect(client.askFinanceAgent).toHaveBeenCalledWith({ session_id: SECOND_ID, question: "Use my CSV", include_context: true }, expect.any(Function));
    fireEvent.click(screen.getByRole("button", { name: "New chat" }));
    expect(screen.getByRole("heading", { name: "Bundled demo ledger" })).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Ask about your spending, budget, or savings"), { target: { value: "Use bundled data" } });
    fireEvent.click(screen.getByRole("button", { name: "Send message" }));
    await waitFor(() => expect(client.createFinanceSession).toHaveBeenLastCalledWith({}));
  });

  it("retains the active ledger when a replacement fails", async () => {
    const saved = detail();
    saved.summary.ledger_source = "upload";
    saved.summary.upload_name = "current.csv";
    window.history.replaceState({}, "", `/chat/${THREAD_ID}`);
    const client = mockClient([saved]);
    client.updateChatThread.mockRejectedValue(new Error("CSV missing required columns: amount"));
    render(<App client={client} />);
    await screen.findByRole("heading", { name: "current.csv" });
    fireEvent.change(screen.getByLabelText("Ledger CSV"), { target: { files: [csvFile("bad.csv", "bad,data")] } });
    expect(await screen.findByRole("alert")).toHaveTextContent("CSV missing required columns");
    expect(screen.getByRole("heading", { name: "current.csv" })).toBeInTheDocument();
    expect(screen.getByText("Savings are RM200.")).toBeInTheDocument();
  });

  it("preserves the composer and confirms global rules without creating a chat", async () => {
    const client = mockClient();
    client.parseBudgetRules.mockResolvedValue({ rules: [{ rule_id: "new_rule", source_text: "Save 25%", supported: true }] });
    render(<App client={client} />);
    await screen.findByText("Agent service connected");
    fireEvent.change(screen.getByLabelText("Ask about your spending, budget, or savings"), { target: { value: "Keep my draft" } });
    fireEvent.click(screen.getAllByRole("button", { name: "Settings" })[0]);
    fireEvent.change(screen.getByLabelText("Natural-language rules"), { target: { value: "Save 25%" } });
    fireEvent.blur(screen.getByLabelText("Natural-language rules"));
    fireEvent.click(screen.getByRole("button", { name: "Parse rules" }));
    await screen.findByRole("heading", { name: "Compiled preview" });
    expect(client.updateAppSettings).not.toHaveBeenCalledWith(expect.objectContaining({ budget_rules: expect.anything() }));
    fireEvent.click(screen.getByRole("button", { name: "Confirm these rules" }));
    await waitFor(() => expect(client.updateAppSettings).toHaveBeenCalledWith({ rules_text: "Save 25%", rules_draft: "Save 25%", budget_rules: [{ rule_id: "new_rule", source_text: "Save 25%", supported: true }] }));
    expect(client.createFinanceSession).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Back to chat" }));
    expect(screen.getByLabelText("Ask about your spending, budget, or savings")).toHaveValue("Keep my draft");
  });

  it("keeps milestones while settings is open during an answer", async () => {
    const client = mockClient([detail()]);
    window.history.replaceState({}, "", `/chat/${THREAD_ID}`);
    let progress!: (envelope: TraceEnvelope) => void;
    let finish!: (result: AgentResult) => void;
    client.askFinanceAgent.mockImplementation((_input, callback) => { progress = callback!; return new Promise((resolve) => { finish = resolve; }); });
    render(<App client={client} />);
    await screen.findByRole("heading", { name: "August review" });
    fireEvent.change(screen.getByLabelText("Ask about your spending, budget, or savings"), { target: { value: "Running question" } });
    fireEvent.click(screen.getByRole("button", { name: "Send message" }));
    await waitFor(() => expect(client.askFinanceAgent).toHaveBeenCalledOnce());
    fireEvent.click(screen.getAllByRole("button", { name: "Settings" })[0]);
    expect(screen.getByLabelText("Max agent steps")).toBeEnabled();
    act(() => progress({ version: 1, thread_id: THREAD_ID, turn_id: THREAD_ID, event: { sequence: 1, timestamp: "2026-09-30T08:00:00Z", operation_id: "prompt", stage: "prompt", state: "completed", payload: { question: "Running question" } } }));
    fireEvent.change(screen.getByLabelText("Max agent steps"), { target: { value: "25" } });
    fireEvent.blur(screen.getByLabelText("Max agent steps"));
    await waitFor(() => expect(client.updateAppSettings).toHaveBeenCalledWith({ max_agent_steps: 25 }));
    fireEvent.click(screen.getByRole("button", { name: "Back to chat" }));
    expect(screen.getByText("Running question")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Replace CSV" })).toBeDisabled();
    await act(async () => finish(result));
  });

  it("supports direct settings routes and reports validation and save errors", async () => {
    window.history.replaceState({}, "", "/settings");
    const client = mockClient();
    client.updateAppSettings.mockRejectedValue(new Error("disk full"));
    render(<App client={client} />);
    const input = await screen.findByLabelText("Compact after turns");
    fireEvent.change(input, { target: { value: "3" } });
    fireEvent.blur(input);
    expect(screen.getByText("Enter a whole number from 5 to 100.")).toBeInTheDocument();
    expect(client.updateAppSettings).not.toHaveBeenCalled();
    fireEvent.change(input, { target: { value: "25" } });
    fireEvent.blur(input);
    expect(await screen.findByRole("alert")).toHaveTextContent("disk full");
    fireEvent.click(screen.getByRole("button", { name: "Back to chat" }));
    expect(window.location.pathname).toBe("/");
  });
});

it("accepts dropped CSVs and preserves staged data when returning from settings", async () => {
  const client = mockClient();
  client.createFinanceSession.mockResolvedValueOnce({ session_id: SECOND_ID, as_of_date: "2026-09-01", context_mode: "auto", transaction_count: 1, budget_rules: [], compaction_turns: 15, max_agent_steps: 15, ledger_source: "upload", upload_name: "dropped.csv" });
  render(<App client={client} />);
  await screen.findByText("Agent service connected");
  fireEvent.drop(screen.getByRole("region", { name: "Chat ledger" }), { dataTransfer: { files: [csvFile("dropped.csv")] } });
  await screen.findByRole("heading", { name: "dropped.csv" });
  fireEvent.click(screen.getAllByRole("button", { name: "Settings" })[0]);
  fireEvent.click(screen.getByRole("button", { name: "Back to chat" }));
  expect(screen.getByRole("heading", { name: "dropped.csv" })).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "New chat" }));
  await waitFor(() => expect(client.closeFinanceSession).toHaveBeenCalledWith({ session_id: SECOND_ID }));
  expect(screen.getByRole("heading", { name: "Bundled demo ledger" })).toBeInTheDocument();
});
