import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import App from "./App";
import type { AgentResult, ChatThreadDetail, ChatThreadSummary, SessionInfo } from "./types";


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
    ledger_source: "demo",
  };
  return {
    connect: vi.fn().mockResolvedValue(undefined),
    close: vi.fn().mockResolvedValue(undefined),
    listChatThreads: vi.fn().mockImplementation(async () => ({ threads: [...records.values()].map((thread) => thread.summary), skipped_files: 0 })),
    getChatThread: vi.fn().mockImplementation(async (threadId: string) => {
      const thread = records.get(threadId);
      if (!thread) throw new Error("Unknown chat thread.");
      return thread;
    }),
    createFinanceSession: vi.fn().mockResolvedValue(created),
    askFinanceAgent: vi.fn().mockImplementation(async ({ session_id, question }: { session_id: string; question: string }) => {
      const next = detail(session_id, question.length > 48 ? `${question.slice(0, 47)}…` : question);
      next.turns[0].question = question;
      records.set(session_id, next);
      return result;
    }),
    updateChatThread: vi.fn().mockImplementation(async ({ thread_id, title, context_mode, compaction_turns }) => {
      const current = records.get(thread_id) ?? detail(thread_id);
      const next = {
        ...current,
        summary: { ...current.summary, title: title ?? current.summary.title },
        context_mode: context_mode ?? current.context_mode,
        compaction_turns: compaction_turns ?? current.compaction_turns,
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

  it("shows immutable saved-chat data and persists mutable context settings", async () => {
    window.history.replaceState({}, "", `/chat/${THREAD_ID}`);
    const client = mockClient([detail()]);
    render(<App client={client} />);
    await screen.findByRole("heading", { name: "August review" });
    fireEvent.click(screen.getAllByRole("button", { name: "Settings" })[0]);

    expect(await screen.findByText("Start a new chat to use a different ledger, date, or rule set.")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Strategy"), { target: { value: "summary" } });
    await waitFor(() => expect(client.updateChatThread).toHaveBeenCalledWith({ thread_id: THREAD_ID, context_mode: "summary" }));
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
