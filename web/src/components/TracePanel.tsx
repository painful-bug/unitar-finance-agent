import { useEffect, useRef, useState, type KeyboardEvent } from "react";

import { MarkdownContent } from "./MarkdownContent";
import { ToolActivity } from "./ToolActivity";
import type { ChatTurn, ExecutionTraceEvent, TraceEvent } from "../types";

function label(value: string): string {
  const spaced = value.replaceAll("_", " ");
  return spaced.charAt(0).toUpperCase() + spaced.slice(1);
}

function object(value: unknown): Record<string, unknown> | null {
  return value !== null && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : null;
}

function TraceValue({ value }: { value: unknown }) {
  if (Array.isArray(value)) return value.length ? <ol className="trace-values">{value.map((item, index) => <li key={index}><TraceValue value={item} /></li>)}</ol> : <span>None</span>;
  const fields = object(value);
  if (fields) return <dl className="trace-fields">{Object.entries(fields).map(([key, item]) => <div key={key}><dt>{label(key)}</dt><dd><TraceValue value={item} /></dd></div>)}</dl>;
  return <span className="trace-value">{value == null ? "—" : String(value)}</span>;
}

const STAGES = {
  prompt: { icon: "↗", title: "User prompt" },
  context: { icon: "◈", title: "Context preparation" },
  model: { icon: "◇", title: "Model request" },
  tool: { icon: "⚒", title: "Tool execution" },
  outcome: { icon: "✓", title: "Final outcome" },
};

function operations(events: ExecutionTraceEvent[]) {
  const paired = new Map<string, ExecutionTraceEvent>();
  for (const event of [...events].sort((a, b) => a.sequence - b.sequence)) {
    const previous = paired.get(event.operation_id);
    paired.set(event.operation_id, { ...previous, ...event, payload: { ...previous?.payload, ...event.payload } });
  }
  return [...paired.values()];
}

function StageCard({ event, interrupted }: { event: ExecutionTraceEvent; interrupted: boolean }) {
  const stage = STAGES[event.stage];
  const state = interrupted && event.state === "started" ? "interrupted" : event.state;
  const status = state === "started" ? "Running" : label(state);
  const payload = event.payload;
  const tool = typeof payload.tool === "string" ? payload.tool : "Unknown tool";
  const args = object(payload.arguments);
  const result = object(payload.result);
  const content = payload.content ?? payload.answer ?? payload.question;
  const error = typeof payload.error === "string" ? payload.error : null;
  const title = event.stage === "tool" ? label(tool) : event.stage === "context" && event.operation_id.endsWith("-jev") ? "Jev compaction" : event.operation_id.includes("summary") ? "Summary compaction" : stage.title;
  return (
    <article className={`trace-stage is-${event.stage} is-${state}`}>
      <header className="trace-stage-header">
        <span className="trace-icon" aria-hidden="true">{state === "failed" ? "!" : state === "warning" || state === "interrupted" ? "△" : stage.icon}</span>
        <h4>{title}</h4><span className="trace-status">{status}</span>
      </header>
      <p className="trace-stage-meta">{event.step != null && `Step ${event.step} · `}{new Date(event.timestamp).toLocaleTimeString()}{event.duration_ms != null && ` · ${(event.duration_ms / 1000).toFixed(2)}s`}</p>
      {typeof content === "string" && content && <MarkdownContent content={content} />}
      {typeof payload.message === "string" && <p>{payload.message}</p>}
      {error && <MarkdownContent content={error} />}
      {payload.fallback_reason != null && <p className="trace-warning">Fallback: {String(payload.fallback_reason)}</p>}
      {event.stage === "context" && (
        <>
          {typeof payload.strategy === "string" && <p>Strategy: <strong>{payload.strategy}</strong></p>}
          {typeof payload.before_tokens === "number" && <p>{payload.before_tokens.toLocaleString()} → {Number(payload.after_tokens ?? payload.before_tokens).toLocaleString()} estimated tokens</p>}
          {Array.isArray(payload.decisions) && payload.decisions.length > 0 && <details><summary>Compaction decisions ({payload.decisions.length})</summary><TraceValue value={payload.decisions} /></details>}
        </>
      )}
      {event.stage === "model" && (
        <>
          {typeof payload.model === "string" && <p>Model: {payload.model}</p>}
          {typeof payload.message_count === "number" && <p>{payload.message_count} input messages · {Number(payload.tool_count ?? 0)} available tools</p>}
          {Array.isArray(payload.tool_calls) && payload.tool_calls.length > 0 && <details><summary>Selected tools ({payload.tool_calls.length})</summary><TraceValue value={payload.tool_calls} /></details>}
        </>
      )}
      {event.stage === "tool" && state !== "started" && <ToolActivity event={{ step: event.step ?? 0, tool, arguments: args, result, error }} showTechnicalDetails={false} />}
      {event.stage === "outcome" && <p>{label(String(payload.status ?? status))} · {Number(payload.steps ?? 0)} agent steps</p>}
      <details className="trace-disclosure"><summary>Captured details</summary><TraceValue value={payload} />{event.tool_call_id && <p>Tool call: <code>{event.tool_call_id}</code></p>}</details>
    </article>
  );
}

function TurnTrace({ turn, number }: { turn: ChatTurn; number: number }) {
  const events = turn.execution_trace ?? [];
  return (
    <section className="trace-turn" aria-label={`Trace for prompt ${number}`}>
      <header className="trace-turn-heading"><h3>{number}. {turn.question}</h3><p><time dateTime={turn.created_at}>{new Date(turn.created_at).toLocaleString()}</time> · {turn.state === "pending" ? "Running" : turn.state === "interrupted" ? "Interrupted" : label(turn.result?.status ?? "complete")}</p></header>
      {turn.state === "interrupted" && <p className="trace-warning" role="status">Execution was interrupted. Captured milestones remain available.</p>}
      {turn.execution_trace_version !== 1 ? (
        <>
          <p className="trace-warning">Limited historical trace: only previously saved tool results, context, and the answer are available.</p>
          {(turn.result?.trace ?? []).map((event: TraceEvent, index) => <ToolActivity key={index} event={event} showTechnicalDetails={false} />)}
          {turn.result?.context && <details><summary>Saved context report</summary><TraceValue value={turn.result.context} /></details>}
          {turn.result && <div className={`trace-stage is-outcome ${turn.result.status === "ok" ? "" : "is-failed"}`}><MarkdownContent content={turn.result.answer} /></div>}
        </>
      ) : events.length ? operations(events).map((event) => <StageCard key={event.operation_id} event={event} interrupted={turn.state === "interrupted"} />) : <p className="context-empty">{turn.state === "pending" ? "Waiting for the first execution milestone…" : "No execution milestones were captured."}</p>}
    </section>
  );
}

interface TracePanelProps {
  turns: ChatTurn[];
  optimisticQuestion: string | null;
  selectedTurnId: string | null;
  onSelectTurn: (id: string | null) => void;
  open: boolean;
  onClose: () => void;
}

export function TracePanel({ turns, optimisticQuestion, selectedTurnId, onSelectTurn, open, onClose }: TracePanelProps) {
  const [raw, setRaw] = useState(false);
  const [compact, setCompact] = useState(() => window.innerWidth <= 1180);
  const panel = useRef<HTMLElement>(null);
  const closeButton = useRef<HTMLButtonElement>(null);
  const list = useRef<HTMLDivElement>(null);
  const follow = useRef(true);
  const shown = selectedTurnId ? turns.filter((turn) => turn.turn_id === selectedTurnId) : turns;
  const revision = shown.map((turn) => `${turn.turn_id}:${turn.execution_trace?.length ?? 0}:${turn.state}`).join("|");

  useEffect(() => {
    const resize = () => setCompact(window.innerWidth <= 1180);
    window.addEventListener("resize", resize);
    return () => window.removeEventListener("resize", resize);
  }, []);
  useEffect(() => { if (open) closeButton.current?.focus(); }, [open]);
  useEffect(() => {
    if (open && follow.current && list.current) list.current.scrollTop = list.current.scrollHeight;
  }, [open, revision]);
  useEffect(() => {
    follow.current = true;
    if (list.current) list.current.scrollTop = 0;
  }, [selectedTurnId]);

  const keys = (event: KeyboardEvent<HTMLElement>) => {
    if (!open) return;
    if (event.key === "Escape") { event.preventDefault(); onClose(); return; }
    if (!compact || event.key !== "Tab") return;
    const controls = [...(panel.current?.querySelectorAll<HTMLElement>("button:not(:disabled), select, summary, a[href], [tabindex='0']") ?? [])].filter((item) => item.offsetParent !== null && !item.closest("details:not([open])") || item.tagName === "SUMMARY" && item.offsetParent !== null);
    const first = controls[0], last = controls.at(-1);
    if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus(); }
    else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus(); }
  };
  const fullscreen = async () => {
    try {
      if (document.fullscreenElement) await document.exitFullscreen();
      else await panel.current?.requestFullscreen();
    } catch { /* Inspector stays usable if fullscreen is unavailable. */ }
  };

  return (
    <aside ref={panel} id="agent-trace" className={`context-inspector trace-inspector ${open ? "is-open" : ""}`} role={compact ? "dialog" : undefined} aria-label="Agent trace" aria-modal={compact && open ? true : undefined} aria-hidden={!open} inert={!open} onKeyDown={keys}>
      <div className="inspector-header"><div><p className="eyebrow">Trace</p><h2>Agent execution</h2></div><div className="header-actions"><button className="icon-button" aria-label="Toggle trace fullscreen" onClick={() => void fullscreen()}>⛶</button><button ref={closeButton} className="icon-button" aria-label="Close trace" onClick={onClose}>×</button></div></div>
      <div className="trace-controls"><label htmlFor="trace-prompt">Prompt</label><select id="trace-prompt" value={selectedTurnId ?? ""} onChange={(event) => onSelectTurn(event.target.value || null)}><option value="">All prompts ({turns.length + (optimisticQuestion ? 1 : 0)})</option>{turns.map((turn, index) => <option key={turn.turn_id} value={turn.turn_id}>{index + 1}. {turn.question}</option>)}</select><div className="context-tabs" role="group" aria-label="Trace display"><button aria-pressed={!raw} onClick={() => setRaw(false)}>Timeline</button><button aria-pressed={raw} onClick={() => setRaw(true)}>Raw JSON</button></div></div>
      <p className="sr-only" role="status">{shown.some((turn) => turn.state === "pending") || optimisticQuestion ? "Agent trace is updating live." : "Agent trace is ready."}</p>
      <div ref={list} className="context-list trace-list" onScroll={() => { const node = list.current; if (node) follow.current = node.scrollHeight - node.scrollTop - node.clientHeight < 80; }}>
        {open && (raw ? <pre className="trace-json">{JSON.stringify(shown, null, 2)}</pre> : shown.map((turn) => <TurnTrace key={turn.turn_id} turn={turn} number={turns.findIndex((item) => item.turn_id === turn.turn_id) + 1} />))}
        {open && !selectedTurnId && optimisticQuestion && <section className="trace-turn"><h3>{turns.length + 1}. {optimisticQuestion}</h3><p role="status">Submitting prompt… Waiting for the server to accept it.</p></section>}
        {open && !shown.length && !optimisticQuestion && <p className="context-empty">{selectedTurnId ? "The selected prompt is unavailable." : "Ask a question to see its agent trace here."}</p>}
      </div>
    </aside>
  );
}
