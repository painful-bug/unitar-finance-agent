import { useEffect, useMemo, useRef, useState, type KeyboardEvent } from "react";

import { MarkdownContent } from "./MarkdownContent";
import { ToolActivity } from "./ToolActivity";
import type { ContextDecision, ContextMessage, ContextReport, TraceEvent } from "../types";


type ContextTab = "before" | "after";

function contentText(content: unknown): string {
  if (typeof content === "string") return content;
  return content == null ? "" : JSON.stringify(content, null, 2);
}

function jsonObject(value: unknown): Record<string, unknown> | null {
  if (typeof value === "object" && value !== null && !Array.isArray(value)) return value as Record<string, unknown>;
  if (typeof value !== "string") return null;
  try {
    const parsed: unknown = JSON.parse(value);
    return typeof parsed === "object" && parsed !== null && !Array.isArray(parsed)
      ? (parsed as Record<string, unknown>)
      : null;
  } catch {
    return null;
  }
}

function actionFor(id: string | undefined, decisions: ContextDecision[]): string | undefined {
  return decisions.find((item) => item.tool_call_id === id)?.action;
}

function ActionBadge({ action }: { action?: string }) {
  if (!action) return null;
  return <span className={`action-badge is-${action}`}>{action}</span>;
}

function MessageCard({
  message,
  number,
  decisions,
  toolResults,
}: {
  message: ContextMessage;
  number: number;
  decisions: ContextDecision[];
  toolResults: Map<string, ContextMessage>;
}) {
  const rawRole = typeof message.role === "string" ? message.role : "unknown";
  const role = rawRole === "system" && contentText(message.content).startsWith("Lossy summary") ? "summary" : rawRole;
  return (
    <article className={`context-message is-${role}`}>
      <header>
        <span>{String(number).padStart(2, "0")} · {role}</span>
        {message.tool_call_id && <code>{message.tool_call_id}</code>}
        <ActionBadge action={actionFor(message.tool_call_id, decisions)} />
      </header>
      {message.content != null && contentText(message.content) && <MarkdownContent content={contentText(message.content)} />}
      {(message.tool_calls ?? []).map((call, index) => {
        const id = call.id;
        const resultMessage = id ? toolResults.get(id) : undefined;
        const event: TraceEvent = {
          step: number,
          tool: call.function?.name ?? "unknown_tool",
          arguments: jsonObject(call.function?.arguments),
          result: jsonObject(resultMessage?.content),
        };
        return (
          <div className="context-tool" key={id ?? index}>
            <ActionBadge action={actionFor(id, decisions)} />
            <ToolActivity event={event} />
          </div>
        );
      })}
    </article>
  );
}

interface ContextPanelProps {
  context: ContextReport | null;
  open: boolean;
  onClose: () => void;
}

export function ContextPanel({ context, open, onClose }: ContextPanelProps) {
  const [tab, setTab] = useState<ContextTab>("before");
  const [compact, setCompact] = useState(() => window.innerWidth <= 1180);
  const previousContext = useRef(context);
  const panel = useRef<HTMLElement>(null);
  const closeButton = useRef<HTMLButtonElement>(null);
  const before = context?.before_messages ?? [];
  const after = context?.after_messages ?? [];
  const source = tab === "before" ? before : after;
  const messages = source.filter((message) => message.role !== "tool");
  const toolResults = useMemo(
    () => new Map(source.filter((message) => message.role === "tool" && message.tool_call_id).map((message) => [message.tool_call_id as string, message])),
    [source],
  );
  const beforeTokens = context?.before_tokens ?? 0;
  const afterTokens = context?.after_tokens ?? 0;
  const reduction = beforeTokens ? Math.round((1 - afterTokens / beforeTokens) * 100) : 0;

  useEffect(() => {
    if (previousContext.current !== context && context?.strategy && context.strategy !== "none") setTab("after");
    previousContext.current = context;
  }, [context]);

  useEffect(() => {
    const resize = () => setCompact(window.innerWidth <= 1180);
    window.addEventListener("resize", resize);
    return () => window.removeEventListener("resize", resize);
  }, []);

  useEffect(() => {
    if (open) closeButton.current?.focus();
  }, [open]);

  const handleKeys = (event: KeyboardEvent<HTMLElement>) => {
    if (!open) return;
    if (event.key === "Escape") {
      event.preventDefault();
      onClose();
      return;
    }
    if (!compact || event.key !== "Tab") return;
    const controls = [...(panel.current?.querySelectorAll<HTMLElement>("button:not(:disabled), summary, a[href]") ?? [])]
      .filter((item) => item.offsetParent !== null);
    const first = controls[0];
    const last = controls.at(-1);
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last?.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first?.focus();
    }
  };

  const toggleFullscreen = async () => {
    try {
      if (document.fullscreenElement) await document.exitFullscreen();
      else await panel.current?.requestFullscreen();
    } catch {
      // The inline inspector remains available when fullscreen is denied.
    }
  };

  return (
    <aside
      ref={panel}
      id="live-context"
      className={`context-inspector ${open ? "is-open" : ""}`}
      role={compact ? "dialog" : undefined}
      aria-label="Conversation context"
      aria-modal={compact && open ? true : undefined}
      aria-hidden={!open}
      onKeyDown={handleKeys}
    >
      <div className="inspector-header">
        <div>
          <p className="eyebrow">Context</p>
          <h2>{context?.strategy ?? "No compaction"}</h2>
        </div>
        <div className="header-actions">
          <button className="icon-button" type="button" aria-label="Toggle context fullscreen" onClick={() => void toggleFullscreen()}>⛶</button>
          <button ref={closeButton} className="icon-button" type="button" aria-label="Close context" onClick={onClose}>×</button>
        </div>
      </div>

      <div className="context-metrics">
        <span>{beforeTokens.toLocaleString()} → {afterTokens.toLocaleString()} tokens</span>
        <span>{reduction}% smaller</span>
      </div>
      {context?.fallback_reason && <div className="context-warning"><MarkdownContent content={`Fallback: ${context.fallback_reason}`} /></div>}

      <div className="context-tabs" role="tablist" aria-label="Context messages">
        <button type="button" role="tab" aria-selected={tab === "before"} onClick={() => setTab("before")}>Before</button>
        <button type="button" role="tab" aria-selected={tab === "after"} onClick={() => setTab("after")}>Model input</button>
      </div>

      <div className="context-list" role="tabpanel">
        {messages.length ? messages.map((message, index) => (
          <MessageCard
            key={`${tab}-${index}`}
            message={message}
            number={index + 1}
            decisions={context?.decisions ?? []}
            toolResults={toolResults}
          />
        )) : (
          <p className="context-empty">Ask a question to inspect the canonical and model-facing context.</p>
        )}
      </div>
    </aside>
  );
}
