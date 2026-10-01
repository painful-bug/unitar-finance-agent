import { useCallback, useEffect, useRef, useState } from "react";

import { ChatPanel } from "./components/ChatPanel";
import { ContextPanel } from "./components/ContextPanel";
import { SettingsPanel } from "./components/SettingsPanel";
import { ThreadSidebar } from "./components/ThreadSidebar";
import { TracePanel } from "./components/TracePanel";
import { FinanceMcpClient } from "./lib/mcp";
import { loadTheme, saveTheme, type Theme } from "./lib/preferences";
import type {
  AppSettings,
  UpdateAppSettingsInput,
  BudgetRule,
  ChatThreadDetail,
  ChatThreadSummary,
  ContextReport,
  SessionInfo,
} from "./types";


type ConnectionStatus = "connecting" | "connected" | "error";
type FinanceClient = Pick<
  FinanceMcpClient,
  | "getAppSettings"
  | "updateAppSettings"
  | "closeFinanceSession"
  | "connect"
  | "close"
  | "parseBudgetRules"
  | "createFinanceSession"
  | "askFinanceAgent"
  | "listChatThreads"
  | "getChatThread"
  | "updateChatThread"
  | "deleteChatThread"
>;

interface UploadLedger {
  name: string;
  session: SessionInfo;
  text: string;
}

interface AppProps {
  client?: FinanceClient;
}

const THREAD_ROUTE = /^\/chat\/([0-9a-f-]{36})\/?$/i;

function errorMessage(error: unknown, fallback: string): string {
  return error instanceof Error ? error.message : fallback;
}

function routedThreadId(): string | null {
  return window.location.pathname.match(THREAD_ROUTE)?.[1] ?? null;
}

export default function App({ client: suppliedClient }: AppProps = {}) {
  const [client] = useState<FinanceClient>(() => suppliedClient ?? new FinanceMcpClient());
  const [connectionStatus, setConnectionStatus] = useState<ConnectionStatus>("connecting");
  const [connectionError, setConnectionError] = useState("");
  const [threads, setThreads] = useState<ChatThreadSummary[]>([]);
  const [skippedThreads, setSkippedThreads] = useState(0);
  const [activeThread, setActiveThread] = useState<ChatThreadDetail | null>(null);
  const [loadingThread, setLoadingThread] = useState(false);
  const [globalError, setGlobalError] = useState("");
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(window.location.pathname === "/settings");
  const [contextOpen, setContextOpen] = useState(false);
  const [traceOpen, setTraceOpen] = useState(false);
  const [traceSelection, setTraceSelection] = useState<string | null>(null);
  const traceButton = useRef<HTMLButtonElement>(null);
  const traceReturnFocus = useRef<HTMLElement | null>(null);
  const requestRevision = useRef(0);
  const [deleteTarget, setDeleteTarget] = useState<ChatThreadSummary | null>(null);
  const deleteDialog = useRef<HTMLDialogElement>(null);
  const mobileMenuButton = useRef<HTMLButtonElement>(null);
  const sidebarReturnFocus = useRef<HTMLElement | null>(null);
  const contextButton = useRef<HTMLButtonElement>(null);

  const [upload, setUpload] = useState<UploadLedger | null>(null);
  const [uploadError, setUploadError] = useState("");
  const [uploadPending, setUploadPending] = useState(false);
  const uploadRevision = useRef(0);
  const draftSession = useRef<string | null>(null);
  const [appSettings, setAppSettings] = useState<AppSettings | null>(null);
  const [rulesText, setRulesText] = useState("");
  const [saveStatus, setSaveStatus] = useState<"idle" | "saving" | "saved" | "error">("idle");
  const [settingsError, setSettingsError] = useState("");
  const settingsQueue = useRef<Promise<unknown>>(Promise.resolve());
  const returnPath = useRef(window.history.state?.returnPath ?? "/");
  const [prompt, setPrompt] = useState("");
  const [chatError, setChatError] = useState("");
  const [asking, setAsking] = useState(false);
  const [compacting, setCompacting] = useState(false);
  const [optimisticQuestion, setOptimisticQuestion] = useState<string | null>(null);
  const askingRef = useRef(false);
  const stablePath = useRef(window.location.pathname);
  const runningChatPath = useRef<string | null>(null);
  const [theme, setTheme] = useState<Theme>(() => {
    const selected = loadTheme();
    document.documentElement.dataset.theme = selected;
    return selected;
  });

  const [parsedRules, setParsedRules] = useState<BudgetRule[] | null>(null);
  const [parsedText, setParsedText] = useState("");
  const [rulesConfirmation, setRulesConfirmation] = useState("");
  const [warnings, setWarnings] = useState<string[]>([]);
  const [parsing, setParsing] = useState(false);
  const [rulesError, setRulesError] = useState("");
  const ruleInputRevision = useRef(0);
  const compactionTurns = appSettings?.compaction_turns ?? 15;
  const pendingRun = activeThread?.turns.some((turn) => turn.state === "pending") ?? false;
  const busy = asking || pendingRun;
  const liveContext: ContextReport | null = (activeThread?.turns ?? [])
    .slice(activeThread?.ledger_changes?.at(-1)?.after_turn_count ?? 0)
    .reverse()
    .find((turn) => turn.result?.context)?.result?.context ?? null;

  const clearUpload = useCallback(() => {
    uploadRevision.current += 1;
    const old = draftSession.current;
    draftSession.current = null;
    if (old) void client.closeFinanceSession({ session_id: old }).catch(() => undefined);
    setUpload(null);
    setUploadError("");
    setUploadPending(false);
  }, [client]);

  const refreshThreads = useCallback(async () => {
    const result = await client.listChatThreads();
    setThreads(result.threads);
    setSkippedThreads(result.skipped_files);
  }, [client]);

  const loadThread = useCallback(async (threadId: string) => {
    setLoadingThread(true);
    setGlobalError("");
    try {
      const detail = await client.getChatThread(threadId);
      setActiveThread(detail);
      askingRef.current = detail.turns.some((turn) => turn.state === "pending");
      runningChatPath.current = `/chat/${detail.summary.thread_id}`;
      setOptimisticQuestion(null);
      setChatError("");
      document.title = `${detail.summary.title} · Finance Agent`;
    } catch (error) {
      setActiveThread(null);
      setGlobalError(errorMessage(error, "Could not load this chat."));
    } finally {
      setLoadingThread(false);
    }
  }, [client]);

  const connectAndLoad = useCallback(async () => {
    setConnectionStatus("connecting");
    setConnectionError("");
    try {
      await client.connect();
      setConnectionStatus("connected");
      const settings = await client.getAppSettings();
      setAppSettings(settings);
      setRulesText(settings.rules_draft);
      await refreshThreads();
      const threadId = routedThreadId() ?? (window.location.pathname === "/settings" ? returnPath.current.match(THREAD_ROUTE)?.[1] : null);
      if (threadId) await loadThread(threadId);
    } catch (error) {
      setConnectionStatus("error");
      setConnectionError(errorMessage(error, "Agent service unavailable."));
    }
  }, [client, loadThread, refreshThreads]);

  useEffect(() => {
    const initialLoad = window.setTimeout(() => void connectAndLoad(), 0);
    const navigateHistory = () => {
      const isSettings = window.location.pathname === "/settings";
      const threadId = routedThreadId();
      if (askingRef.current && !isSettings && window.location.pathname !== runningChatPath.current) {
        window.history.pushState({}, "", stablePath.current);
        return;
      }
      const previousPath = stablePath.current;
      stablePath.current = window.location.pathname;
      setSettingsOpen(isSettings);
      setTraceOpen(false);
      setContextOpen(false);
      if (isSettings) {
        returnPath.current = window.history.state?.returnPath ?? returnPath.current;
      } else if (threadId) {
        if (!askingRef.current) { clearUpload(); void loadThread(threadId); }
      } else if (!askingRef.current) {
        if (previousPath !== "/settings") clearUpload();
        setActiveThread(null);
        document.title = "Personal Finance Agent";
      }
    };
    window.addEventListener("popstate", navigateHistory);
    return () => {
      requestRevision.current += 1;
      window.clearTimeout(initialLoad);
      window.removeEventListener("popstate", navigateHistory);
      const draft = draftSession.current;
      void (async () => {
        if (draft) await client.closeFinanceSession({ session_id: draft }).catch(() => undefined);
        await client.close();
      })();
    };
  }, [client, connectAndLoad, loadThread, clearUpload]);

  useEffect(() => {
    if (!pendingRun || asking || !activeThread) return;
    let cancelled = false;
    let timer: number;
    const threadId = activeThread.summary.thread_id;
    const poll = async () => {
      try {
        const detail = await client.getChatThread(threadId);
        if (cancelled) return;
        setActiveThread(detail);
        const running = detail.turns.some((turn) => turn.state === "pending");
        askingRef.current = running;
        if (!running) { await refreshThreads(); return; }
      } catch (error) {
        if (cancelled) return;
        setChatError(errorMessage(error, "Could not recover the running trace."));
      }
      if (!cancelled) timer = window.setTimeout(() => void poll(), 1000);
    };
    timer = window.setTimeout(() => void poll(), 1000);
    return () => { cancelled = true; window.clearTimeout(timer); };
  }, [pendingRun, asking, activeThread, client, refreshThreads]);

  useEffect(() => {
    const dialog = deleteDialog.current;
    if (!dialog) return;
    if (deleteTarget && !dialog.open) dialog.showModal();
    if (!deleteTarget && dialog.open) dialog.close();
  }, [deleteTarget]);

  const saveSettings = (input: UpdateAppSettingsInput): Promise<AppSettings | null> => {
    setSaveStatus("saving");
    setSettingsError("");
    const request = settingsQueue.current.then(async () => {
      setSaveStatus("saving");
      try {
        const settings = await client.updateAppSettings(input);
        setAppSettings(settings);
        setSaveStatus("saved");
        return settings;
      } catch (error) {
        setSaveStatus("error");
        setSettingsError(errorMessage(error, "Could not save settings."));
        return null;
      }
    });
    settingsQueue.current = request;
    return request;
  };

  const selectUpload = async (file: File | null) => {
    if (busy || loadingThread) return;
    const revision = ++uploadRevision.current;
    setUploadError("");
    setUploadPending(true);
    try {
      if (file && file.size > 10_000_000) throw new Error("CSV exceeds 10 MB.");
      const text = file ? new TextDecoder("utf-8", { fatal: true }).decode(await file.arrayBuffer()) : undefined;
      if (revision !== uploadRevision.current) return;
      if (activeThread) {
        const detail = await client.updateChatThread({ thread_id: activeThread.summary.thread_id,
          ...(file ? { csv_text: text, upload_name: file.name } : { use_bundled_data: true }) });
        if (revision !== uploadRevision.current) return;
        setActiveThread(detail);
        setContextOpen(false);
        setTraceOpen(false);
        await refreshThreads();
      } else if (file && text !== undefined) {
        const session = await client.createFinanceSession({ csv_text: text, upload_name: file.name });
        if (revision !== uploadRevision.current) {
          void client.closeFinanceSession({ session_id: session.session_id });
          return;
        }
        const old = draftSession.current;
        draftSession.current = session.session_id;
        if (old) void client.closeFinanceSession({ session_id: old }).catch(() => undefined);
        setUpload({ name: file.name, text, session });
      } else {
        clearUpload();
      }
    } catch (error) {
      if (revision === uploadRevision.current) setUploadError(errorMessage(error, "Could not read this CSV. Use a UTF-8 CSV file."));
    } finally {
      if (revision === uploadRevision.current) setUploadPending(false);
    }
  };

  const updateRulesText = (text: string) => {
    ruleInputRevision.current += 1;
    setRulesConfirmation("");
    setRulesText(text);
  };

  const parseRules = async () => {
    const revision = ruleInputRevision.current;
    setParsing(true);
    setRulesError("");
    setRulesConfirmation("");
    try {
      const preview = await client.parseBudgetRules({ rules_text: rulesText, csv_text: upload?.text });
      if (revision !== ruleInputRevision.current) return;
      setParsedRules(preview.rules);
      setParsedText(rulesText);
      setWarnings(preview.warnings ?? []);
    } catch (error) {
      if (revision === ruleInputRevision.current) setRulesError(errorMessage(error, "Could not parse budget rules."));
    } finally { setParsing(false); }
  };

  const confirmRules = async () => {
    if (!parsedRules?.length || parsedText !== rulesText) return;
    const revision = ruleInputRevision.current;
    const saved = await saveSettings({ rules_draft: rulesText, rules_text: rulesText, budget_rules: parsedRules });
    if (saved && revision === ruleInputRevision.current) {
      setParsedRules(null);
      setWarnings([]);
      setRulesConfirmation("Rules confirmed and saved for every chat.");
    }
  };

  const resetRules = async () => {
    const settings = await saveSettings({ reset_rules: true });
    if (!settings) return;
    updateRulesText(settings.rules_draft);
    setParsedRules(null);
    setWarnings([]);
    setRulesError("");
  };

  const createSession = async (): Promise<SessionInfo> => {
    if (upload) return upload.session;
    return client.createFinanceSession({});
  };

  const openSettings = () => {
    if (!settingsOpen) returnPath.current = stablePath.current;
    stablePath.current = "/settings";
    window.history.pushState({ returnPath: returnPath.current }, "", "/settings");
    setSettingsOpen(true);
    setSidebarOpen(false);
    setContextOpen(false);
    setTraceOpen(false);
    void client.getAppSettings().then((settings) => {
      setAppSettings(settings);
      setRulesText((current) => current === appSettings?.rules_draft ? settings.rules_draft : current);
    }).catch((error) => setSettingsError(errorMessage(error, "Could not load settings.")));
  };

  const closeSettings = () => {
    const path = activeThread ? `/chat/${activeThread.summary.thread_id}` : returnPath.current;
    stablePath.current = path;
    window.history.pushState({}, "", path);
    setSettingsOpen(false);
    window.setTimeout(() => document.getElementById("chat-prompt")?.focus(), 0);
  };

  const navigateToThread = async (threadId: string) => {
    if (askingRef.current) return;
    clearUpload();
    setSettingsOpen(false);
    stablePath.current = `/chat/${threadId}`;
    window.history.pushState({}, "", stablePath.current);
    setSidebarOpen(false);
    setContextOpen(false);
    setTraceOpen(false);
    setTraceSelection(null);
    await loadThread(threadId);
    document.getElementById("chat-prompt")?.focus();
  };

  const newChat = () => {
    if (askingRef.current) return;
    clearUpload();
    setSettingsOpen(false);
    stablePath.current = "/";
    window.history.pushState({}, "", stablePath.current);
    setActiveThread(null);
    setOptimisticQuestion(null);
    setPrompt("");
    setChatError("");
    setGlobalError("");
    setContextOpen(false);
    setTraceOpen(false);
    setTraceSelection(null);
    setSidebarOpen(false);
    document.title = "Personal Finance Agent";
    window.setTimeout(() => document.getElementById("chat-prompt")?.focus(), 0);
  };

  const openSidebar = () => {
    sidebarReturnFocus.current = document.activeElement as HTMLElement;
    setSidebarOpen(true);
  };

  const closeSidebar = () => {
    setSidebarOpen(false);
    (sidebarReturnFocus.current?.isConnected ? sidebarReturnFocus.current : mobileMenuButton.current)?.focus();
  };

  const closeContext = () => {
    setContextOpen(false);
    if (document.fullscreenElement?.id === "live-context") void document.exitFullscreen().catch(() => undefined);
    contextButton.current?.focus();
  };

  const closeTrace = () => {
    setTraceOpen(false);
    if (document.fullscreenElement?.id === "agent-trace") void document.exitFullscreen().catch(() => undefined);
    (traceReturnFocus.current?.isConnected ? traceReturnFocus.current : traceButton.current)?.focus();
  };

  const viewTrace = (turnId: string | null) => {
    traceReturnFocus.current = document.activeElement as HTMLElement;
    setTraceSelection(turnId);
    setContextOpen(false);
    if (document.fullscreenElement?.id === "live-context") void document.exitFullscreen().catch(() => undefined);
    setTraceOpen(true);
  };

  const askQuestion = async () => {
    const question = prompt.trim();
    if (!question || askingRef.current || busy || uploadPending || !appSettings || connectionStatus !== "connected") return;
    askingRef.current = true;
    setAsking(true);
    setChatError("");
    setOptimisticQuestion(question);
    setPrompt("");
    const turns = (activeThread?.turns.length ?? 0) - (activeThread?.ledger_changes?.at(-1)?.after_turn_count ?? 0);
    setCompacting(turns + 1 >= compactionTurns);
    let sessionId = activeThread?.summary.thread_id ?? null;
    runningChatPath.current = sessionId ? `/chat/${sessionId}` : null;
    let createdSession: SessionInfo | null = null;
    let recoveredPending = false;
    const submittedTurnCount = activeThread?.turns.length ?? 0;
    const revision = ++requestRevision.current;
    try {
      if (!sessionId) {
        const created = await createSession();
        createdSession = created;
        sessionId = created.session_id;
        runningChatPath.current = `/chat/${sessionId}`;
        draftSession.current = null;
        returnPath.current = `/chat/${sessionId}`;
        if (stablePath.current === "/settings") {
          window.history.replaceState({ returnPath: returnPath.current }, "", "/settings");
        } else {
          stablePath.current = `/chat/${sessionId}`;
          window.history.pushState({}, "", stablePath.current);
        }
      }
      await client.askFinanceAgent({
        session_id: sessionId,
        question,
        include_context: true,
      }, (envelope) => {
        if (revision !== requestRevision.current || envelope.thread_id !== sessionId) return;
        const event = envelope.event;
        setActiveThread((current) => {
          if (current && current.summary.thread_id !== envelope.thread_id) return current;
          const base = current ?? (createdSession ? {
            summary: { thread_id: envelope.thread_id, title: question, created_at: event.timestamp, updated_at: event.timestamp, turn_count: 0, ledger_source: createdSession.ledger_source, upload_name: createdSession.upload_name },
            as_of_date: createdSession.as_of_date, context_mode: createdSession.context_mode,
            transaction_count: createdSession.transaction_count, budget_rules: createdSession.budget_rules,
            compaction_turns: createdSession.compaction_turns, max_agent_steps: createdSession.max_agent_steps, turns: [],
          } : null);
          if (!base) return current;
          const turn = base.turns.find((item) => item.turn_id === envelope.turn_id);
          if (turn?.execution_trace?.some((item) => item.sequence === event.sequence)) return current;
          if (!turn && event.stage !== "prompt") return current;
          const nextTurn = { ...turn, turn_id: envelope.turn_id, question: turn?.question ?? question,
            created_at: turn?.created_at ?? event.timestamp, state: "pending" as const, execution_trace_version: 1 as const,
            execution_trace: [...(turn?.execution_trace ?? []), event].sort((a, b) => a.sequence - b.sequence) };
          const nextTurns = turn ? base.turns.map((item) => item.turn_id === turn.turn_id ? nextTurn : item) : [...base.turns, nextTurn];
          return { ...base, summary: { ...base.summary, turn_count: nextTurns.length, updated_at: event.timestamp }, turns: nextTurns };
        });
        if (event.stage === "prompt") setOptimisticQuestion(null);
      });
      const detail = await client.getChatThread(sessionId);
      setActiveThread(detail);
      setOptimisticQuestion(null);
      document.title = `${detail.summary.title} · Finance Agent`;
      await refreshThreads();
    } catch (error) {
      setChatError(errorMessage(error, "Could not ask the finance agent."));
      if (sessionId) {
        try {
          const detail = await client.getChatThread(sessionId);
          recoveredPending = detail.turns.some((turn) => turn.state === "pending");
          setActiveThread(detail);
          if (detail.turns.length > submittedTurnCount) setOptimisticQuestion(null);
          await refreshThreads();
        } catch {
          // Keep the submitted question visible when it could not be persisted.
        }
      }
    } finally {
      if (requestRevision.current === revision) requestRevision.current += 1;
      askingRef.current = recoveredPending;
      setAsking(false);
      setCompacting(false);
    }
  };

  const renameThread = async (threadId: string, title: string) => {
    setGlobalError("");
    try {
      const detail = await client.updateChatThread({ thread_id: threadId, title });
      if (activeThread?.summary.thread_id === threadId) setActiveThread(detail);
      await refreshThreads();
    } catch (error) {
      setGlobalError(errorMessage(error, "Could not rename this chat."));
    }
  };

  const deleteThread = async () => {
    if (!deleteTarget) return;
    setGlobalError("");
    try {
      await client.deleteChatThread(deleteTarget.thread_id);
      if (activeThread?.summary.thread_id === deleteTarget.thread_id) newChat();
      setDeleteTarget(null);
      await refreshThreads();
    } catch (error) {
      setGlobalError(errorMessage(error, "Could not delete this chat."));
      setDeleteTarget(null);
    }
  };

  const toggleTheme = () => {
    const next: Theme = theme === "dark" ? "light" : "dark";
    document.documentElement.dataset.theme = next;
    setTheme(next);
    saveTheme(next);
  };

  const headerTitle = activeThread?.summary.title ?? "New chat";
  const headerMeta = activeThread
    ? `${activeThread.summary.ledger_source === "demo" ? "Demo ledger" : activeThread.summary.upload_name ?? "Uploaded ledger"} · ${activeThread.transaction_count} transactions · ${activeThread.as_of_date}`
    : "Use the bundled ledger, or add your own CSV right here.";

  return (
    <>
      <a className="skip-link" href={settingsOpen ? "#settings-title" : "#chat-main"}>Skip to {settingsOpen ? "settings" : "conversation"}</a>
      <div className={`app-shell ${sidebarCollapsed ? "sidebar-collapsed" : ""} ${!settingsOpen && (contextOpen || traceOpen) ? "context-open" : ""}`}>
        <ThreadSidebar
          threads={threads}
          activeId={activeThread?.summary.thread_id ?? null}
          connectionStatus={connectionStatus}
          disabled={busy || loadingThread}
          mobileOpen={sidebarOpen}
          collapsed={sidebarCollapsed}
          theme={theme}
          onCloseMobile={closeSidebar}
          onToggleCollapsed={() => setSidebarCollapsed((current) => !current)}
          onNewChat={newChat}
          onSelect={(threadId) => void navigateToThread(threadId)}
          onRename={renameThread}
          onDelete={setDeleteTarget}
          settingsActive={settingsOpen}
          onOpenSettings={openSettings}
          onToggleTheme={toggleTheme}
        />

        <main id="chat-main" className="chat-main" hidden={settingsOpen}>
          <header className="chat-header">
            <button ref={mobileMenuButton} className="icon-button mobile-menu-button" type="button" aria-label="Open conversations" onClick={openSidebar}>☰</button>
            <div className="chat-heading"><h1>{headerTitle}</h1><p>{headerMeta}</p></div>
            <div className="header-actions">
              <button ref={contextButton} className="header-button" type="button" aria-pressed={contextOpen} onClick={() => { if (contextOpen) closeContext(); else { setTraceOpen(false); setContextOpen(true); } }}>Context</button>
              <button ref={traceButton} className="header-button" type="button" aria-pressed={traceOpen} onClick={() => { if (traceOpen) closeTrace(); else { traceReturnFocus.current = traceButton.current; setContextOpen(false); setTraceOpen(true); } }}>Trace</button>
              <button className="header-button" type="button" onClick={openSettings}>Settings</button>
            </div>
          </header>

          {(connectionStatus === "error" || globalError || skippedThreads > 0) && (
            <div className="service-banner" aria-live="polite">
              <p>{connectionStatus === "error" ? connectionError : globalError || `${skippedThreads} saved chat file${skippedThreads === 1 ? " was" : "s were"} skipped because they could not be read.`}</p>
              {connectionStatus === "error" && <button type="button" onClick={() => void connectAndLoad()}>Retry</button>}
            </div>
          )}

          <ChatPanel
            thread={activeThread}
            prompt={prompt}
            optimisticQuestion={optimisticQuestion}
            pending={busy || loadingThread || uploadPending || !appSettings || connectionStatus !== "connected"}
            compacting={compacting}
            error={chatError}
            onPromptChange={setPrompt}
            onSubmit={() => void askQuestion()}
            onViewTrace={viewTrace}
            ledger={activeThread ? { ledger_source: activeThread.summary.ledger_source, upload_name: activeThread.summary.upload_name,
              transaction_count: activeThread.transaction_count, as_of_date: activeThread.as_of_date } : upload?.session ?? null}
            uploadPending={uploadPending}
            uploadError={uploadError}
            ledgerDisabled={busy || loadingThread || connectionStatus !== "connected"}
            onUpload={(file) => void selectUpload(file)}
          />
        </main>

        <ContextPanel context={liveContext} open={!settingsOpen && contextOpen} onClose={closeContext} />
        <TracePanel key={activeThread?.summary.thread_id ?? "new"} turns={activeThread?.turns ?? []} optimisticQuestion={optimisticQuestion} selectedTurnId={traceSelection} onSelectTurn={setTraceSelection} open={!settingsOpen && traceOpen} onClose={closeTrace} />

        {settingsOpen && <SettingsPanel
          settings={appSettings}
          rulesText={rulesText}
          onRulesTextChange={updateRulesText}
          onSaveDraft={() => { if (rulesText !== appSettings?.rules_draft) void saveSettings({ rules_draft: rulesText }); }}
          onSave={(input) => void saveSettings(input)}
          parsedRules={parsedRules}
          confirmation={rulesConfirmation}
          warnings={warnings}
          previewCurrent={Boolean(parsedRules && parsedText === rulesText)}
          parsing={parsing}
          error={rulesError || settingsError || connectionError || globalError}
          saveStatus={saveStatus}
          onParse={() => void parseRules()}
          onConfirm={() => void confirmRules()}
          onReset={() => void resetRules()}
          onBack={closeSettings}
          onOpenSidebar={openSidebar}
        />}

        <dialog ref={deleteDialog} className="confirm-dialog" aria-labelledby="delete-chat-title" onClose={() => setDeleteTarget(null)} onCancel={() => setDeleteTarget(null)}>
          <h2 id="delete-chat-title">Delete chat?</h2>
          <p><strong>{deleteTarget?.title}</strong> and its local ledger snapshot will be permanently removed.</p>
          <div className="button-row end"><button className="secondary-button" type="button" onClick={() => setDeleteTarget(null)}>Cancel</button><button className="danger-button" type="button" onClick={() => void deleteThread()}>Delete</button></div>
        </dialog>
      </div>
    </>
  );
}
