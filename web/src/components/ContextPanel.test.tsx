import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { ContextReport } from "../types";
import { ContextPanel } from "./ContextPanel";


const context: ContextReport = {
  strategy: "summary",
  before_tokens: 200,
  after_tokens: 100,
  fallback_reason: "Jev unavailable",
  decisions: [{ tool_call_id: "keep-call", action: "keep" }],
  before_messages: [
    { role: "system", content: "<img src=x onerror=alert(1)> **Safe instructions**" },
    {
      role: "assistant",
      content: null,
      tool_calls: [{ id: "keep-call", function: { name: "lookup_transactions", arguments: '{"month":"2026-08","kind":"expense"}' } }],
    },
    { role: "tool", tool_call_id: "keep-call", content: '{"count":2,"total":"120.00","transactions":[]}' },
  ],
  after_messages: [
    { role: "system", content: "Lossy summary of earlier session history:\nExact RM values." },
    { role: "user", content: "Newest question" },
  ],
};

afterEach(cleanup);

describe("ContextPanel", () => {
  it("renders metrics, safe Markdown, decisions, and human-readable tool activity", () => {
    const { container } = render(<ContextPanel context={context} open onClose={() => undefined} />);

    expect(screen.getByText("200 → 100 tokens")).toBeInTheDocument();
    expect(screen.getByText("50% smaller")).toBeInTheDocument();
    expect(screen.getByText(/Fallback: Jev unavailable/)).toBeInTheDocument();
    expect(screen.getByText("Looked up expense transactions")).toBeInTheDocument();
    expect(screen.getByText("keep")).toBeInTheDocument();
    expect(screen.getByText("Safe instructions")).toBeInTheDocument();
    expect(container.querySelector("img")).toBeNull();
  });

  it("switches between canonical and model-input messages", () => {
    render(<ContextPanel context={context} open onClose={() => undefined} />);
    fireEvent.click(screen.getByRole("tab", { name: "Model input" }));

    expect(screen.queryByText("Looked up expense transactions")).not.toBeInTheDocument();
    expect(screen.getByText(/Lossy summary of earlier/)).toBeInTheDocument();
    expect(screen.getByText("Newest question")).toBeInTheDocument();
  });

  it("selects model input when a compacted report arrives", () => {
    const { rerender } = render(<ContextPanel context={null} open onClose={() => undefined} />);
    rerender(<ContextPanel context={context} open onClose={() => undefined} />);
    expect(screen.getByRole("tab", { name: "Model input" })).toHaveAttribute("aria-selected", "true");
  });

  it("keeps inline viewing when fullscreen is denied", () => {
    const requestFullscreen = vi.fn().mockRejectedValue(new Error("denied"));
    const { container } = render(<ContextPanel context={context} open onClose={() => undefined} />);
    const panel = container.querySelector("#live-context") as HTMLElement;
    panel.requestFullscreen = requestFullscreen;
    fireEvent.click(screen.getByRole("button", { name: "Toggle context fullscreen" }));
    expect(requestFullscreen).toHaveBeenCalledTimes(1);
  });
});
