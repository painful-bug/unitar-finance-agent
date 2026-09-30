import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { useState } from "react";

import { TracePanel } from "./TracePanel";
import type { ChatTurn, ExecutionTraceEvent } from "../types";

function event(sequence: number, state: ExecutionTraceEvent["state"], payload = {}): ExecutionTraceEvent {
  return { sequence, timestamp: "2026-09-30T08:00:00Z", operation_id: "model-1", stage: "model", state, step: 1, payload };
}
const turns: ChatTurn[] = [
  { turn_id: "first", question: "Same question", created_at: "2026-09-30T08:00:00Z", state: "complete", execution_trace_version: 1, execution_trace: [event(1, "started"), event(2, "completed", { content: "First answer" })] },
  { turn_id: "second", question: "Same question", created_at: "2026-09-30T08:01:00Z", state: "pending", execution_trace_version: 1, execution_trace: [event(1, "started", { model: "test-model" })] },
];

function Inspector({ source = turns }: { source?: ChatTurn[] }) {
  const [selected, setSelected] = useState<string | null>(null);
  return <TracePanel turns={source} optimisticQuestion={null} selectedTurnId={selected} onSelectTurn={setSelected} open onClose={() => undefined} />;
}

afterEach(cleanup);

describe("TracePanel", () => {
  it("defaults to all prompts, pairs milestones, and selects identical prompts by ID", () => {
    render(<Inspector />);
    expect(screen.getByLabelText("Prompt")).toHaveValue("");
    expect(screen.getAllByRole("heading", { name: "Model request" })).toHaveLength(2);
    expect(screen.getAllByText("First answer")[0]).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Prompt"), { target: { value: "second" } });
    expect(screen.queryByText("First answer")).not.toBeInTheDocument();
    expect(screen.getByText("Running")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Raw JSON" }));
    const raw = document.querySelector(".trace-json")!;
    expect(JSON.parse(raw.textContent!)).toEqual([turns[1]]);
    fireEvent.change(screen.getByLabelText("Prompt"), { target: { value: "" } });
    expect(JSON.parse(raw.textContent!)).toEqual(turns);
  });

  it("preserves selection and expanded details when a running operation completes", () => {
    const { rerender } = render(<Inspector />);
    fireEvent.change(screen.getByLabelText("Prompt"), { target: { value: "second" } });
    const disclosure = screen.getByText("Captured details").closest("details")!;
    disclosure.open = true;
    const next = [turns[0], { ...turns[1], state: "complete" as const, execution_trace: [...turns[1].execution_trace!, event(2, "completed", { content: "Second answer", nested: { extra: [1, 2, 3] } })] }];
    rerender(<Inspector source={next} />);
    expect(screen.getByLabelText("Prompt")).toHaveValue("second");
    expect(screen.getByText("Captured details").closest("details")).toBe(disclosure);
    expect(disclosure).toHaveAttribute("open");
    expect(screen.getAllByText("Second answer")[0]).toBeInTheDocument();
    expect(screen.getByText("Extra")).toBeInTheDocument();
    expect(document.querySelector("pre")).toBeNull();
  });

  it("does not move readers away from older content when events arrive", () => {
    const { container, rerender } = render(<Inspector />);
    const list = container.querySelector(".trace-list") as HTMLElement;
    Object.defineProperties(list, { scrollHeight: { configurable: true, value: 1000 }, clientHeight: { configurable: true, value: 300 } });
    list.scrollTop = 100;
    fireEvent.scroll(list);
    rerender(<Inspector source={[turns[0], { ...turns[1], execution_trace: [...turns[1].execution_trace!, event(2, "completed")] }]} />);
    expect(list.scrollTop).toBe(100);
    list.scrollTop = 700;
    fireEvent.scroll(list);
    Object.defineProperty(list, "scrollHeight", { configurable: true, value: 1100 });
    rerender(<Inspector source={[turns[0], { ...turns[1], execution_trace: [...turns[1].execution_trace!, event(2, "completed"), { ...event(3, "started"), operation_id: "model-2" }] }]} />);
    expect(list.scrollTop).toBe(1100);
  });

  it("shows historical, interrupted, and empty states without fabricating events", () => {
    const { rerender, container } = render(<Inspector source={[{ ...turns[0], execution_trace_version: null, execution_trace: [] }]} />);
    expect(screen.getByText(/Limited historical trace/)).toBeInTheDocument();
    rerender(<Inspector source={[{ ...turns[1], state: "interrupted" }]} />);
    expect(container.querySelector(".trace-stage.is-interrupted")).not.toBeNull();
    expect(screen.getByText(/Captured milestones remain available/)).toBeInTheDocument();
    rerender(<Inspector source={[]} />);
    expect(screen.getByText("Ask a question to see its agent trace here.")).toBeInTheDocument();
  });

  it("renders safe content, every unknown field, and explicit failures", () => {
    const { container } = render(<Inspector source={[{ ...turns[0], execution_trace: [{ ...event(1, "failed", { tool: "unknown", error: "<img src=x onerror=alert(1)> **Failed safely**", arguments: { seventh: 7 }, result: { nested: { field: "retained" } } }), stage: "tool" }] }]} />);
    expect(container.querySelector(".is-failed")).not.toBeNull();
    expect(container.querySelector("img")).toBeNull();
    expect(screen.getByText("Seventh")).toBeInTheDocument();
    expect(screen.getByText("retained")).toBeInTheDocument();
    expect(container.querySelector("pre")).toBeNull();
  });

  it("makes closed controls inert and closes on Escape", () => {
    const close = vi.fn();
    const { rerender, container } = render(<TracePanel turns={turns} optimisticQuestion={null} selectedTurnId={null} onSelectTurn={() => undefined} open onClose={close} />);
    const panel = container.querySelector("#agent-trace")!;
    expect(screen.getByRole("button", { name: "Close trace" })).toHaveFocus();
    fireEvent.keyDown(panel, { key: "Escape" });
    expect(close).toHaveBeenCalledOnce();
    rerender(<TracePanel turns={turns} optimisticQuestion={null} selectedTurnId={null} onSelectTurn={() => undefined} open={false} onClose={close} />);
    expect(panel).toHaveAttribute("inert");
    expect(within(panel as HTMLElement).queryByText("First answer")).toBeNull();
  });
});
