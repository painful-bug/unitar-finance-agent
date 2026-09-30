import { useEffect, useRef, useState } from "react";

import { MarkdownContent } from "./MarkdownContent";
import type { AppSettings, BudgetRule, UpdateAppSettingsInput } from "../types";

interface SettingsPanelProps {
  settings: AppSettings | null;
  rulesText: string;
  onRulesTextChange: (text: string) => void;
  onSaveDraft: () => void;
  onSave: (input: UpdateAppSettingsInput) => void;
  parsedRules: BudgetRule[] | null;
  warnings: string[];
  previewCurrent: boolean;
  parsing: boolean;
  error: string;
  saveStatus: "idle" | "saving" | "saved" | "error";
  onParse: () => void;
  onConfirm: () => void;
  onReset: () => void;
  onBack: () => void;
  onOpenSidebar: () => void;
}

function RuleList({ rules }: { rules: BudgetRule[] }) {
  return <div className="rule-list">{rules.map((rule) => <article key={rule.rule_id}>
    <div><span className={`status-dot ${rule.supported === false ? "is-warning" : ""}`} aria-hidden="true" /><strong>{rule.source_text}</strong></div>
    <p>{rule.supported === false ? rule.unsupported_reason : `${rule.left?.category ?? rule.left?.metric ?? rule.left?.value ?? ""} ${({ lt: "<", lte: "≤", eq: "=", gte: "≥", gt: ">" } as const)[rule.operator ?? "eq"]} ${rule.right?.value ?? rule.right?.metric ?? ""} ${rule.right?.unit ?? ""}`}</p>
  </article>)}</div>;
}

function NumericSetting({ id, label, value, min, max, onSave }: {
  id: string; label: string; value: number; min: number; max: number; onSave: (value: number) => void;
}) {
  const [draft, setDraft] = useState(String(value));
  const [error, setError] = useState("");
  return <div className="field-stack">
    <label htmlFor={id}>{label}</label>
    <input id={id} type="number" min={min} max={max} value={draft} aria-invalid={Boolean(error)} aria-describedby={`${id}-help`}
      onChange={(event) => { setDraft(event.target.value); setError(""); }} onBlur={() => {
        const number = Number(draft);
        if (!draft.trim() || !Number.isInteger(number) || number < min || number > max) {
          setError(`Enter a whole number from ${min} to ${max}.`);
        } else if (number !== value) onSave(number);
      }} />
    <p id={`${id}-help`} className={error ? "field-error" : "field-help"}>{error || `${min}–${max} · saved when you leave this field`}</p>
  </div>;
}

export function SettingsPanel(props: SettingsPanelProps) {
  const title = useRef<HTMLHeadingElement>(null);
  useEffect(() => { title.current?.focus(); }, []);
  const settings = props.settings;
  const confirmed = settings?.rules_text === props.rulesText;
  return <main className="settings-page" aria-labelledby="settings-title">
    <header className="settings-page-header">
      <div className="settings-topline">
        <button className="icon-button mobile-menu-button" type="button" aria-label="Open conversations" onClick={props.onOpenSidebar}>☰</button>
        <button className="back-link" type="button" onClick={props.onBack}><span aria-hidden="true">← </span>Back to chat</button>
        <span className={`save-state is-${props.saveStatus}`} role="status">{props.saveStatus === "saving" ? "Saving…" : props.saveStatus === "error" ? "Changes not saved" : props.saveStatus === "saved" ? "All changes saved" : "Applies to every chat"}</span>
      </div>
      <p className="eyebrow">Your workspace</p>
      <h1 ref={title} tabIndex={-1} id="settings-title">Make it work your way.</h1>
      <p className="settings-intro">One set of preferences for every conversation. Changes apply to the next answer.</p>
      <nav className="settings-section-nav" aria-label="Settings sections">
        <a href="#budget-settings">Budget rules</a><a href="#context-settings">Context</a><a href="#execution-settings">Agent execution</a><a href="#evaluation-settings">Evaluation</a>
      </nav>
    </header>
    <div className="settings-page-body">
      {props.error && <div className="settings-error" role="alert"><MarkdownContent content={props.error} /></div>}
      {!settings ? <p role="status">Loading workspace settings…</p> : <div className="settings-dashboard">
        <section id="budget-settings" className="settings-card budget-settings-card">
          <div className="settings-card-heading"><span className="settings-card-icon" aria-hidden="true">≋</span><div><h2>Budget rules</h2><p>Define your limits in your own words.</p></div><span className="settings-badge">All chats</span></div>
          <div className="field-stack"><label htmlFor="budget-rules">Natural-language rules</label>
            <textarea id="budget-rules" rows={7} value={props.rulesText} onChange={(event) => props.onRulesTextChange(event.target.value)} onBlur={props.onSaveDraft} placeholder="For example: Save at least 20% of monthly income." />
            <p className="field-help">Preview the compiled rules, then confirm to apply them. Editing a draft keeps your active rules in place.</p>
          </div>
          <div className="button-row"><button className="primary-button" type="button" disabled={props.parsing || !props.rulesText.trim()} onClick={props.onParse}>{props.parsing ? "Parsing…" : "Parse rules"}</button><button className="secondary-button" type="button" onClick={props.onReset}>Use defaults</button></div>
          {props.parsedRules && props.previewCurrent && <div className="rule-preview">
            <h3>Compiled preview</h3><RuleList rules={props.parsedRules} />
            {props.warnings.map((warning) => <div className="settings-warning" key={warning}><MarkdownContent content={warning} /></div>)}
            <details className="tool-disclosure technical-details"><summary>Technical details</summary><pre>{JSON.stringify(props.parsedRules, null, 2)}</pre></details>
            <button className="primary-button" type="button" disabled={!props.parsedRules.length || props.saveStatus === "saving"} onClick={props.onConfirm}>Confirm these rules</button>
          </div>}
          {props.parsedRules && !props.previewCurrent && <p className="settings-warning">Your draft changed. Parse it again before confirming.</p>}
          <div className="active-rules"><div className="active-rules-heading"><h3>Active rules</h3><span className="settings-badge">{settings.budget_rules.length} rules</span></div>
            <p className="field-help" role="status">{confirmed ? "These rules are active for every chat." : "Your previous confirmed rules are still active for every chat."}</p><RuleList rules={settings.budget_rules} /></div>
        </section>
        <div className="settings-side-cards">
          <section id="context-settings" className="settings-card">
            <div className="settings-card-heading"><span className="settings-card-icon" aria-hidden="true">◈</span><div><h2>Conversation context</h2><p>Keep long conversations focused.</p></div></div>
            <div className="field-stack"><label htmlFor="context-mode">Strategy</label><select id="context-mode" value={settings.context_mode} onChange={(event) => props.onSave({ context_mode: event.target.value as AppSettings["context_mode"] })}><option value="auto">Auto</option><option value="jev">Jev</option><option value="summary">Summary</option></select><p className="field-help">Auto selects the available compaction strategy.</p></div>
            <NumericSetting key={`turns-${settings.compaction_turns}`} id="compaction-turns" label="Compact after turns" value={settings.compaction_turns} min={5} max={100} onSave={(value) => props.onSave({ compaction_turns: value })} />
          </section>
          <section id="execution-settings" className="settings-card">
            <div className="settings-card-heading"><span className="settings-card-icon" aria-hidden="true">↗</span><div><h2>Agent execution</h2><p>Set room for reasoning and tools.</p></div></div>
            <NumericSetting key={`steps-${settings.max_agent_steps}`} id="max-agent-steps" label="Max agent steps" value={settings.max_agent_steps} min={1} max={100} onSave={(value) => props.onSave({ max_agent_steps: value })} />
            <p className="field-help">Each answer can take up to this many model-and-tool steps. An answer already running keeps its original limit.</p>
          </section>
          <section id="evaluation-settings" className="settings-card">
            <div className="settings-card-heading"><span className="settings-card-icon" aria-hidden="true">✓</span><div><h2>Evaluation</h2><p>Choose the judge for the evaluation script.</p></div></div>
            <div className="field-stack"><label htmlFor="evaluation-judge">Evaluation judge</label><select id="evaluation-judge" value={settings.evaluation_judge} onChange={(event) => props.onSave({ evaluation_judge: event.target.value as AppSettings["evaluation_judge"] })}><option value="auto">Auto</option><option value="jev">Jev</option><option value="llm">LLM</option></select><p className="field-help">Auto tries Jev, then uses the LLM if Jev fails or is uncertain. Run the Python script to evaluate.</p></div>
          </section>
          <div className="settings-footnote"><span aria-hidden="true">↻</span><p>Saved on this agent, shared across chats, and remembered after a restart.</p></div>
        </div>
      </div>}
    </div>
  </main>;
}
