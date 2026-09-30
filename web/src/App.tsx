import { useCallback, useEffect, useRef, useState } from "react";

import { ChatPanel } from "./components/ChatPanel";
import { ContextPanel } from "./components/ContextPanel";
import { SettingsPanel, type LedgerSource } from "./components/SettingsPanel";
import { ThreadSidebar } from "./components/ThreadSidebar";
import { FinanceMcpClient } from "./lib/mcp";
import {
  DEFAULT_RULES_TEXT,
  loadCompactionTurns,
  loadTheme,
  RULE_EDITOR_VERSION,
  loadRulePreferences,
  rulesSignature,
  saveRulePreferences,
  saveCompactionTurns,
  saveTheme,
  type Theme,
  type RulePreferences,
} from "./lib/preferences";
import type {
  BudgetRule,
  ChatThreadDetail,
  ChatThreadSummary,
  ContextMode,
  ContextReport,
  CreateFinanceSessionInput,
  SessionInfo,
  UpdateChatThreadInput,
} from "./types";


type ConnectionStatus = "connecting" | "connected" | "error";
type FinanceClient = Pick<
  FinanceMcpClient,
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
  bytes: Uint8Array;
  text: string;
}

interface AppProps {
  client?: FinanceClient;
}

const DEMO_SIGNATURE_BYTES = new TextEncoder().encode("demo");
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
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [contextOpen, setContextOpen] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState<ChatThreadSummary | null>(null);
  const deleteDialog = useRef<HTMLDialogElement>(null);
  const mobileMenuButton = useRef<HTMLButtonElement>(null);
  const contextButton = useRef<HTMLButtonElement>(null);

  const [source, setSource] = useState<LedgerSource>("demo");
  const [upload, setUpload] = useState<UploadLedger | null>(null);
  const [uploadName, setUploadName] = useState<string | null>(null);
  const [uploadError, setUploadError] = useState("");
  const [uploadPending, setUploadPending] = useState(false);
  const uploadRevision = useRef(0);
  const ruleInputRevision = useRef(0);
  const [draftContextMode, setDraftContextMode] = useState<ContextMode>("auto");
  const [overrideDate, setOverrideDate] = useState(false);
  const [asOfDate, setAsOfDate] = useState("");
  const [draftCompactionTurns, setDraftCompactionTurns] = useState(loadCompactionTurns);
  const [prompt, setPrompt] = useState("");
  const [chatError, setChatError] = useState("");
  const [asking, setAsking] = useState(false);
  const [compacting, setCompacting] = useState(false);
  const [optimisticQuestion, setOptimisticQuestion] = useState<string | null>(null);
  const askingRef = useRef(false);
  const stablePath = useRef(window.location.pathname);
  const [theme, setTheme] = useState<Theme>(() => {
    const selected = loadTheme();
    document.documentElement.dataset.theme = selected;
    return selected;
  });

  const [preferences, setPreferences] = useState<RulePreferences>(loadRulePreferences);
  const [parsedRules, setParsedRules] = useState<BudgetRule[] | null>(preferences.confirmedRules);
  const [warnings, setWarnings] = useState<string[]>([]);
  const [parsedSignature, setParsedSignature] = useState<string | null>(preferences.confirmedSignature);
  const [signatureResult, setSignatureResult] = useState<{ ledgerBytes: Uint8Array; rulesText: string; signature: string } | null>(null);
  const [parsing, setParsing] = useState(false);
  const [rulesError, setRulesError] = useState("");

  const ledgerBytes = source === "upload" && upload ? upload.bytes : DEMO_SIGNATURE_BYTES;
  const contextMode = activeThread?.context_mode ?? draftContextMode;
  const compactionTurns = activeThread?.compaction_turns ?? draftCompactionTurns;
  const liveContext: ContextReport | null = [...(activeThread?.turns ?? [])]
    .reverse()
    .find((turn) => turn.result?.context)?.result?.context ?? null;

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
      await refreshThreads();
      const threadId = routedThreadId();
      if (threadId) await loadThread(threadId);
    } catch (error) {
      setConnectionStatus("error");
      setConnectionError(errorMessage(error, "Agent service unavailable."));
    }
  }, [client, loadThread, refreshThreads]);

  useEffect(() => {
    const initialLoad = window.setTimeout(() => void connectAndLoad(), 0);
    const navigateHistory = () => {
      if (askingRef.current) {
        window.history.pushState({}, "", stablePath.current);
        return;
      }
      stablePath.current = window.location.pathname;
      const threadId = routedThreadId();
      if (threadId) void loadThread(threadId);
      else {
        setActiveThread(null);
        setContextOpen(false);
        document.title = "Personal Finance Agent";
      }
    };
    window.addEventListener("popstate", navigateHistory);
    return () => {
      window.clearTimeout(initialLoad);
      window.removeEventListener("popstate", navigateHistory);
      void client.close();
    };
  }, [client, connectAndLoad, loadThread]);

  useEffect(() => {
    let current = true;
    void rulesSignature(ledgerBytes, preferences.rulesText).then((signature) => {
      if (current) setSignatureResult({ ledgerBytes, rulesText: preferences.rulesText, signature });
    });
    return () => { current = false; };
  }, [ledgerBytes, preferences.rulesText]);

  useEffect(() => {
    const dialog = deleteDialog.current;
    if (!dialog) return;
    if (deleteTarget && !dialog.open) dialog.showModal();
    if (!deleteTarget && dialog.open) dialog.close();
  }, [deleteTarget]);

  const currentSignature = signatureResult?.ledgerBytes === ledgerBytes && signatureResult.rulesText === preferences.rulesText
    ? signatureResult.signature
    : null;
  const signaturePending = currentSignature === null;
  const previewCurrent = Boolean(parsedRules && currentSignature && parsedSignature === currentSignature);
  const confirmedCurrent = Boolean(preferences.confirmedRules && currentSignature && preferences.confirmedSignature === currentSignature);

  const csvText = (): string | undefined => {
    if (source === "demo") return undefined;
    if (!upload) throw new Error(uploadError || "Choose a CSV file first.");
    return upload.text;
  };

  const selectUpload = (file: File | null) => {
    const revision = ++uploadRevision.current;
    ruleInputRevision.current += 1;
    setUpload(null);
    setUploadName(file?.name ?? null);
    setUploadError("");
    if (!file) { setUploadPending(false); return; }
    setUploadPending(true);
    void file.arrayBuffer()
      .then((buffer) => {
        const bytes = new Uint8Array(buffer);
        const text = new TextDecoder("utf-8", { fatal: true }).decode(bytes);
        if (revision === uploadRevision.current) setUpload({ name: file.name, bytes, text });
      })
      .catch(() => {
        if (revision === uploadRevision.current) setUploadError("Ledger CSV must be valid UTF-8.");
      })
      .finally(() => { if (revision === uploadRevision.current) setUploadPending(false); });
  };

  const updateRulesText = (rulesText: string) => {
    ruleInputRevision.current += 1;
    const next = { ...preferences, rulesText };
    setPreferences(next);
    saveRulePreferences(next);
  };

  const parseRules = async () => {
    const revision = ruleInputRevision.current;
    setParsing(true);
    setRulesError("");
    try {
      const selectedCsv = csvText();
      const signature = await rulesSignature(ledgerBytes, preferences.rulesText);
      const preview = await client.parseBudgetRules({ rules_text: preferences.rulesText, csv_text: selectedCsv });
      if (revision !== ruleInputRevision.current) return;
      const next: RulePreferences = { version: RULE_EDITOR_VERSION, rulesText: preferences.rulesText, confirmedRules: null, confirmedSignature: null };
      setParsedRules(preview.rules);
      setWarnings(preview.warnings ?? []);
      setParsedSignature(signature);
      setPreferences(next);
      saveRulePreferences(next);
    } catch (error) {
      if (revision === ruleInputRevision.current) setRulesError(errorMessage(error, "Could not parse budget rules."));
    } finally { setParsing(false); }
  };

  const confirmRules = () => {
    if (!parsedRules || !currentSignature || parsedSignature !== currentSignature) return;
    const next = { ...preferences, confirmedRules: parsedRules, confirmedSignature: currentSignature };
    setPreferences(next);
    saveRulePreferences(next);
  };

  const resetRules = () => {
    const next: RulePreferences = { version: RULE_EDITOR_VERSION, rulesText: DEFAULT_RULES_TEXT, confirmedRules: null, confirmedSignature: null };
    setPreferences(next);
    setParsedRules(null);
    setWarnings([]);
    setParsedSignature(null);
    setRulesError("");
    saveRulePreferences(next);
  };

  const createSession = async (): Promise<SessionInfo> => {
    const signature = await rulesSignature(ledgerBytes, preferences.rulesText);
    const input: CreateFinanceSessionInput = { context_mode: draftContextMode, compaction_turns: draftCompactionTurns };
    const selectedCsv = csvText();
    if (selectedCsv !== undefined) {
      input.csv_text = selectedCsv;
      input.upload_name = upload?.name ?? null;
    }
    if (overrideDate && asOfDate) input.as_of_date = asOfDate;
    if (preferences.confirmedRules && preferences.confirmedSignature === signature) input.budget_rules = preferences.confirmedRules;
    return client.createFinanceSession(input);
  };

  const navigateToThread = async (threadId: string) => {
    if (askingRef.current) return;
    stablePath.current = `/chat/${threadId}`;
    window.history.pushState({}, "", stablePath.current);
    setSidebarOpen(false);
    setContextOpen(false);
    await loadThread(threadId);
    document.getElementById("chat-prompt")?.focus();
  };

  const newChat = () => {
    if (askingRef.current) return;
    stablePath.current = "/";
    window.history.pushState({}, "", stablePath.current);
    setActiveThread(null);
    setOptimisticQuestion(null);
    setPrompt("");
    setChatError("");
    setGlobalError("");
    setContextOpen(false);
    setSidebarOpen(false);
    document.title = "Personal Finance Agent";
    window.setTimeout(() => document.getElementById("chat-prompt")?.focus(), 0);
  };

  const closeSidebar = () => {
    setSidebarOpen(false);
    mobileMenuButton.current?.focus();
  };

  const closeContext = () => {
    setContextOpen(false);
    contextButton.current?.focus();
  };

  const askQuestion = async () => {
    const question = prompt.trim();
    if (!question || askingRef.current) return;
    askingRef.current = true;
    setAsking(true);
    setChatError("");
    setOptimisticQuestion(question);
    setPrompt("");
    const turns = activeThread?.turns.length ?? 0;
    setCompacting(turns + 1 >= compactionTurns);
    let sessionId = activeThread?.summary.thread_id ?? null;
    try {
      if (!sessionId) {
        const created = await createSession();
        sessionId = created.session_id;
        stablePath.current = `/chat/${sessionId}`;
        window.history.pushState({}, "", stablePath.current);
      }
      await client.askFinanceAgent({
        session_id: sessionId,
        question,
        context_mode: contextMode,
        include_context: true,
        compaction_turns: compactionTurns,
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
          setActiveThread(detail);
          setOptimisticQuestion(null);
          await refreshThreads();
        } catch {
          // Keep the submitted question visible when it could not be persisted.
        }
      }
    } finally {
      askingRef.current = false;
      setAsking(false);
      setCompacting(false);
    }
  };

  const updateThread = async (input: Omit<UpdateChatThreadInput, "thread_id">) => {
    if (!activeThread) return;
    setGlobalError("");
    try {
      const detail = await client.updateChatThread({ thread_id: activeThread.summary.thread_id, ...input });
      setActiveThread(detail);
      await refreshThreads();
    } catch (error) {
      setGlobalError(errorMessage(error, "Could not update this chat."));
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
    : "Configure the ledger in Settings, then start a conversation.";

  return (
    <>
      <a className="skip-link" href="#chat-main">Skip to conversation</a>
      <div className={`app-shell ${sidebarCollapsed ? "sidebar-collapsed" : ""} ${contextOpen ? "context-open" : ""}`}>
        <ThreadSidebar
          threads={threads}
          activeId={activeThread?.summary.thread_id ?? null}
          connectionStatus={connectionStatus}
          disabled={asking || loadingThread}
          mobileOpen={sidebarOpen}
          collapsed={sidebarCollapsed}
          theme={theme}
          onCloseMobile={closeSidebar}
          onToggleCollapsed={() => setSidebarCollapsed((current) => !current)}
          onNewChat={newChat}
          onSelect={(threadId) => void navigateToThread(threadId)}
          onRename={renameThread}
          onDelete={setDeleteTarget}
          onOpenSettings={() => setSettingsOpen(true)}
          onToggleTheme={toggleTheme}
        />

        <main id="chat-main" className="chat-main">
          <header className="chat-header">
            <button ref={mobileMenuButton} className="icon-button mobile-menu-button" type="button" aria-label="Open conversations" onClick={() => setSidebarOpen(true)}>☰</button>
            <div className="chat-heading"><h1>{headerTitle}</h1><p>{headerMeta}</p></div>
            <div className="header-actions">
              <button ref={contextButton} className="header-button" type="button" aria-pressed={contextOpen} onClick={() => contextOpen ? closeContext() : setContextOpen(true)}>Context</button>
              <button className="header-button" type="button" onClick={() => setSettingsOpen(true)}>Settings</button>
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
            pending={asking || loadingThread}
            compacting={compacting}
            error={chatError}
            onPromptChange={setPrompt}
            onSubmit={() => void askQuestion()}
          />
        </main>

        <ContextPanel context={liveContext} open={contextOpen} onClose={closeContext} />

        <SettingsPanel
          open={settingsOpen}
          thread={activeThread}
          source={source}
          onSourceChange={(next) => { ruleInputRevision.current += 1; setSource(next); }}
          uploadName={uploadName}
          onUploadChange={selectUpload}
          uploadError={uploadError}
          uploadPending={uploadPending}
          contextMode={contextMode}
          onContextModeChange={(mode) => activeThread ? void updateThread({ context_mode: mode }) : setDraftContextMode(mode)}
          overrideDate={overrideDate}
          onOverrideDateChange={setOverrideDate}
          asOfDate={asOfDate}
          onAsOfDateChange={setAsOfDate}
          compactionTurns={compactionTurns}
          onCompactionTurnsChange={(turns) => {
            if (activeThread) void updateThread({ compaction_turns: turns });
            else { setDraftCompactionTurns(turns); saveCompactionTurns(turns); }
          }}
          rulesText={preferences.rulesText}
          onRulesTextChange={updateRulesText}
          parsedRules={parsedRules}
          warnings={warnings}
          previewCurrent={previewCurrent}
          confirmedCurrent={confirmedCurrent}
          signaturePending={signaturePending || uploadPending}
          parsing={parsing}
          error={rulesError}
          onParse={() => void parseRules()}
          onConfirm={confirmRules}
          onReset={resetRules}
          onClose={() => setSettingsOpen(false)}
        />

        <dialog ref={deleteDialog} className="confirm-dialog" aria-labelledby="delete-chat-title" onClose={() => setDeleteTarget(null)} onCancel={() => setDeleteTarget(null)}>
          <h2 id="delete-chat-title">Delete chat?</h2>
          <p><strong>{deleteTarget?.title}</strong> and its local ledger snapshot will be permanently removed.</p>
          <div className="button-row end"><button className="secondary-button" type="button" onClick={() => setDeleteTarget(null)}>Cancel</button><button className="danger-button" type="button" onClick={() => void deleteThread()}>Delete</button></div>
        </dialog>
      </div>
    </>
  );
}
