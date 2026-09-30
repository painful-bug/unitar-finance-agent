import { useEffect, useMemo, useRef, useState, type KeyboardEvent } from "react";

import type { ChatThreadSummary } from "../types";
import type { Theme } from "../lib/preferences";


type ConnectionStatus = "connecting" | "connected" | "error";
type ThreadGroup = { label: string; threads: ChatThreadSummary[] };

function dayStart(value: Date): number {
  return new Date(value.getFullYear(), value.getMonth(), value.getDate()).getTime();
}

function groupThreads(threads: ChatThreadSummary[]): ThreadGroup[] {
  const today = dayStart(new Date());
  const day = 86_400_000;
  const groups: ThreadGroup[] = [
    { label: "Today", threads: [] },
    { label: "Yesterday", threads: [] },
    { label: "Previous 7 days", threads: [] },
    { label: "Older", threads: [] },
  ];
  for (const thread of threads) {
    const difference = Math.floor((today - dayStart(new Date(thread.updated_at))) / day);
    const index = difference <= 0 ? 0 : difference === 1 ? 1 : difference <= 7 ? 2 : 3;
    groups[index].threads.push(thread);
  }
  return groups.filter((group) => group.threads.length);
}

interface ThreadSidebarProps {
  threads: ChatThreadSummary[];
  activeId: string | null;
  connectionStatus: ConnectionStatus;
  disabled: boolean;
  mobileOpen: boolean;
  collapsed: boolean;
  theme: Theme;
  settingsActive?: boolean;
  onCloseMobile: () => void;
  onToggleCollapsed: () => void;
  onNewChat: () => void;
  onSelect: (threadId: string) => void;
  onRename: (threadId: string, title: string) => Promise<void>;
  onDelete: (thread: ChatThreadSummary) => void;
  onOpenSettings: () => void;
  onToggleTheme: () => void;
}

export function ThreadSidebar({
  threads,
  activeId,
  connectionStatus,
  disabled,
  mobileOpen,
  collapsed,
  theme,
  settingsActive,
  onCloseMobile,
  onToggleCollapsed,
  onNewChat,
  onSelect,
  onRename,
  onDelete,
  onOpenSettings,
  onToggleTheme,
}: ThreadSidebarProps) {
  const groups = useMemo(() => groupThreads(threads), [threads]);
  const [renaming, setRenaming] = useState<string | null>(null);
  const [renameValue, setRenameValue] = useState("");
  const sidebar = useRef<HTMLElement>(null);
  const mobileClose = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (mobileOpen) mobileClose.current?.focus();
  }, [mobileOpen]);

  const keepMobileFocus = (event: KeyboardEvent<HTMLElement>) => {
    if (!mobileOpen) return;
    if (event.key === "Escape") {
      event.preventDefault();
      onCloseMobile();
      return;
    }
    if (event.key !== "Tab") return;
    const controls = [...(sidebar.current?.querySelectorAll<HTMLElement>("button:not(:disabled), input:not(:disabled), summary, a[href]") ?? [])]
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

  const beginRename = (thread: ChatThreadSummary) => {
    setRenaming(thread.thread_id);
    setRenameValue(thread.title);
  };

  const saveRename = async () => {
    if (!renaming || !renameValue.trim()) return;
    await onRename(renaming, renameValue);
    setRenaming(null);
  };

  return (
    <>
      {mobileOpen && <button className="sidebar-backdrop" aria-label="Close conversations" onClick={onCloseMobile} />}
      <aside
        ref={sidebar}
        className={`thread-sidebar ${collapsed ? "is-collapsed" : ""} ${mobileOpen ? "is-mobile-open" : ""}`}
        role={mobileOpen ? "dialog" : undefined}
        aria-label={mobileOpen ? "Conversations" : undefined}
        aria-modal={mobileOpen || undefined}
        onKeyDown={keepMobileFocus}
      >
        <div className="sidebar-header">
          <span className="brand-mark" aria-hidden="true">F</span>
          <span className="brand-name">Finance Agent</span>
          <button className="icon-button sidebar-collapse" type="button" aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"} onClick={onToggleCollapsed}>
            {collapsed ? "›" : "‹"}
          </button>
          <button ref={mobileClose} className="icon-button sidebar-mobile-close" type="button" aria-label="Close conversations" onClick={onCloseMobile}>×</button>
        </div>

        <button className="new-chat-button" type="button" disabled={disabled} onClick={onNewChat}>
          <span aria-hidden="true">＋</span><span>New chat</span>
        </button>

        <nav className="thread-history" aria-label="Chat history">
          {groups.map((group) => (
            <section className="thread-group" key={group.label}>
              <h2>{group.label}</h2>
              {group.threads.map((thread) => (
                <div className={`thread-row ${activeId === thread.thread_id ? "is-active" : ""}`} key={thread.thread_id}>
                  {renaming === thread.thread_id ? (
                    <input
                      className="thread-rename-input"
                      aria-label={`Rename ${thread.title}`}
                      autoFocus
                      maxLength={100}
                      value={renameValue}
                      onBlur={() => setRenaming(null)}
                      onChange={(event) => setRenameValue(event.target.value)}
                      onKeyDown={(event) => {
                        if (event.key === "Enter") {
                          event.preventDefault();
                          void saveRename();
                        }
                        if (event.key === "Escape") setRenaming(null);
                      }}
                    />
                  ) : (
                    <button
                      className="thread-select"
                      type="button"
                      aria-current={activeId === thread.thread_id ? "page" : undefined}
                      title={thread.title}
                      disabled={disabled}
                      onClick={() => onSelect(thread.thread_id)}
                    >
                      {thread.title}
                    </button>
                  )}
                  <details className="thread-menu">
                    <summary aria-label={`Actions for ${thread.title}`}>•••</summary>
                    <div className="thread-menu-popover">
                      <button type="button" disabled={disabled} onClick={(event) => {
                        event.currentTarget.closest("details")?.removeAttribute("open");
                        beginRename(thread);
                      }}>Rename</button>
                      <button className="danger-action" type="button" disabled={disabled} onClick={(event) => {
                        event.currentTarget.closest("details")?.removeAttribute("open");
                        onDelete(thread);
                      }}>Delete</button>
                    </div>
                  </details>
                </div>
              ))}
            </section>
          ))}
          {!threads.length && <p className="sidebar-empty">Your saved chats will appear here.</p>}
        </nav>

        <footer className="sidebar-footer">
          <div className="connection-state" title={`Agent service ${connectionStatus}`}>
            <span className={`connection-dot is-${connectionStatus}`} aria-hidden="true" />
            <span>Agent service {connectionStatus}</span>
          </div>
          <button type="button" aria-current={settingsActive ? "page" : undefined} onClick={onOpenSettings}><span aria-hidden="true">⚙</span><span>Settings</span></button>
          <button type="button" onClick={onToggleTheme}><span aria-hidden="true">{theme === "dark" ? "☀" : "☾"}</span><span>{theme === "dark" ? "Light mode" : "Dark mode"}</span></button>
        </footer>
      </aside>
    </>
  );
}
