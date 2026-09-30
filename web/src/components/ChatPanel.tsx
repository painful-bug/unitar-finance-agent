import { useEffect, useRef, type KeyboardEvent } from "react";

import { MarkdownContent } from "./MarkdownContent";
import { ToolActivity } from "./ToolActivity";
import type { ChatThreadDetail } from "../types";


interface ChatPanelProps {
  thread: ChatThreadDetail | null;
  prompt: string;
  optimisticQuestion: string | null;
  pending: boolean;
  compacting: boolean;
  error: string;
  onPromptChange: (value: string) => void;
  onSubmit: () => void;
  onViewTrace: (turnId: string | null) => void;
}

export function ChatPanel({
  thread,
  prompt,
  optimisticQuestion,
  pending,
  compacting,
  error,
  onPromptChange,
  onSubmit,
  onViewTrace,
}: ChatPanelProps) {
  const textarea = useRef<HTMLTextAreaElement>(null);
  const end = useRef<HTMLDivElement>(null);
  const turns = thread?.turns ?? [];

  useEffect(() => {
    const input = textarea.current;
    if (!input) return;
    input.style.height = "auto";
    input.style.height = `${Math.min(input.scrollHeight, 200)}px`;
  }, [prompt]);

  useEffect(() => {
    end.current?.scrollIntoView({ block: "end" });
  }, [turns.length, optimisticQuestion, pending]);

  const keyboardSubmit = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key !== "Enter" || event.shiftKey || event.nativeEvent.isComposing) return;
    event.preventDefault();
    onSubmit();
  };

  return (
    <div className="conversation-layout">
      <section className={`conversation-scroll ${!turns.length && !optimisticQuestion ? "is-empty" : ""}`} aria-label="Conversation">
        {!turns.length && !optimisticQuestion ? (
          <div className="empty-chat">
            <span className="empty-mark" aria-hidden="true">F</span>
            <h2>How can I help with your finances?</h2>
            <p>Answers use only the active ledger. Local beta—not financial advice.</p>
          </div>
        ) : (
          <div className="transcript">
            {turns.map((turn) => (
              <div className="turn" key={turn.turn_id}>
                <article className="user-message" aria-label="user message">
                  <MarkdownContent content={turn.question} />
                  <button className="view-trace-button" type="button" onClick={() => onViewTrace(turn.turn_id)}><span aria-hidden="true">◇</span> View trace</button>
                </article>
                {turn.state === "complete" && turn.result ? (
                  <article className="assistant-message" aria-label="assistant message">
                    {(turn.result.trace ?? []).length > 0 && (
                      <div className="tool-stack" aria-label="Tools used">
                        {(turn.result.trace ?? []).map((event, index) => (
                          <ToolActivity event={event} key={`${event.step}-${event.tool}-${index}`} />
                        ))}
                      </div>
                    )}
                    <MarkdownContent content={turn.result.answer} />
                    <p className="answer-meta">
                      {turn.result.status === "ok" ? "Complete" : turn.result.status.replaceAll("_", " ")} · {turn.result.steps} {turn.result.steps === 1 ? "step" : "steps"}
                      {turn.result.context?.strategy && turn.result.context.strategy !== "none" ? ` · ${turn.result.context.strategy} context` : ""}
                    </p>
                  </article>
                ) : turn.state === "interrupted" ? (
                  <p className="turn-error" role="status">The previous response was interrupted. You can send the question again.</p>
                ) : (
                  <p className="pending-response" role="status"><span className="loading-dot" aria-hidden="true" />Thinking…</p>
                )}
              </div>
            ))}
            {optimisticQuestion && !turns.some((turn) => turn.question === optimisticQuestion && turn.state === "pending") && (
              <div className="turn">
                <article className="user-message" aria-label="user message"><MarkdownContent content={optimisticQuestion} /><button className="view-trace-button" type="button" onClick={() => onViewTrace(null)}><span aria-hidden="true">◇</span> View trace</button></article>
                <p className="pending-response" role="status"><span className="loading-dot" aria-hidden="true" />{compacting ? "Compacting context…" : "Checking the ledger…"}</p>
              </div>
            )}
          </div>
        )}
        <div ref={end} />
      </section>

      <div className="composer-region">
        {error && <p className="inline-error" role="alert">{error}</p>}
        <form
          className="composer"
          onSubmit={(event) => {
            event.preventDefault();
            onSubmit();
          }}
        >
          <label className="sr-only" htmlFor="chat-prompt">Ask about your spending, budget, or savings</label>
          <textarea
            ref={textarea}
            id="chat-prompt"
            rows={1}
            value={prompt}
            placeholder="Ask about your spending, budget, or savings"
            disabled={pending}
            onChange={(event) => onPromptChange(event.target.value)}
            onKeyDown={keyboardSubmit}
          />
          <button className="send-button" type="submit" aria-label="Send message" disabled={pending || !prompt.trim()}>
            {pending ? "…" : "↑"}
          </button>
        </form>
        <p className="composer-note">Finance Agent can make mistakes. Verify important decisions.</p>
      </div>
    </div>
  );
}
