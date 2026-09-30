import { useEffect, useRef, type ChangeEvent } from "react";

import { MarkdownContent } from "./MarkdownContent";
import type { BudgetRule, ChatThreadDetail, ContextMode } from "../types";

export type LedgerSource = "demo" | "upload";


interface SettingsPanelProps {
  open: boolean;
  disabled?: boolean;
  thread: ChatThreadDetail | null;
  source: LedgerSource;
  onSourceChange: (source: LedgerSource) => void;
  uploadName: string | null;
  onUploadChange: (file: File | null) => void;
  uploadError: string;
  uploadPending: boolean;
  contextMode: ContextMode;
  onContextModeChange: (mode: ContextMode) => void;
  overrideDate: boolean;
  onOverrideDateChange: (enabled: boolean) => void;
  asOfDate: string;
  onAsOfDateChange: (value: string) => void;
  compactionTurns: number;
  onCompactionTurnsChange: (value: number) => void;
  maxAgentSteps: number;
  onMaxAgentStepsChange: (value: number) => void;
  rulesText: string;
  onRulesTextChange: (value: string) => void;
  parsedRules: BudgetRule[] | null;
  warnings: string[];
  previewCurrent: boolean;
  confirmedCurrent: boolean;
  signaturePending: boolean;
  parsing: boolean;
  error: string;
  onParse: () => void;
  onConfirm: () => void;
  onReset: () => void;
  onClose: () => void;
}

function operandValue(operand: BudgetRule["left"]): string {
  if (!operand) return "";
  return String(operand.metric ?? operand.value ?? "");
}

function comparison(rule: BudgetRule): string {
  if (!rule.supported) return rule.unsupported_reason ?? "Unsupported";
  return `${operandValue(rule.left)} ${rule.operator ?? ""} ${operandValue(rule.right)}`;
}

function RuleList({ rules }: { rules: BudgetRule[] }) {
  return (
    <div className="rule-list">
      {rules.map((rule) => (
        <article key={rule.rule_id}>
          <div><span className={`status-dot ${rule.supported ? "" : "is-warning"}`} aria-hidden="true" /><strong>{rule.source_text}</strong></div>
          <code>{comparison(rule)}</code>
        </article>
      ))}
    </div>
  );
}

export function SettingsPanel(props: SettingsPanelProps) {
  const dialog = useRef<HTMLDialogElement>(null);
  const active = props.thread;

  useEffect(() => {
    const element = dialog.current;
    if (!element) return;
    if (props.open && !element.open) element.showModal();
    if (!props.open && element.open) element.close();
  }, [props.open]);

  const selectFile = (event: ChangeEvent<HTMLInputElement>) => {
    props.onUploadChange(event.target.files?.[0] ?? null);
  };

  return (
    <dialog ref={dialog} className="settings-dialog" aria-labelledby="settings-title" onClose={props.onClose} onCancel={props.onClose}>
      <div className="dialog-header">
        <div><p className="eyebrow">Configuration</p><h2 id="settings-title">Chat settings</h2></div>
        <button className="icon-button" type="button" aria-label="Close settings" onClick={props.onClose}>×</button>
      </div>

      <div className="settings-body">
        {active ? (
          <section className="settings-section">
            <div className="section-heading"><h3>Saved chat</h3><p>Ledger, date, and budget rules are fixed so earlier answers remain reproducible.</p></div>
            <dl className="snapshot-grid">
              <div><dt>Ledger</dt><dd>{active.summary.ledger_source === "demo" ? "Bundled demo" : active.summary.upload_name ?? "Uploaded CSV"}</dd></div>
              <div><dt>As-of date</dt><dd>{active.as_of_date}</dd></div>
              <div><dt>Transactions</dt><dd>{active.transaction_count}</dd></div>
              <div><dt>Budget rules</dt><dd>{active.budget_rules.length}</dd></div>
            </dl>
            <p className="settings-note">Start a new chat to use a different ledger, date, or rule set.</p>
            <RuleList rules={active.budget_rules} />
          </section>
        ) : (
          <section className="settings-section">
            <div className="section-heading"><h3>New chat data</h3><p>These inputs become an immutable snapshot after the first message.</p></div>
            <fieldset className="choice-row">
              <legend>Ledger</legend>
              <label><input type="radio" name="ledger-source" checked={props.source === "demo"} onChange={() => props.onSourceChange("demo")} />Bundled demo</label>
              <label><input type="radio" name="ledger-source" checked={props.source === "upload"} onChange={() => props.onSourceChange("upload")} />Upload CSV</label>
            </fieldset>
            {props.source === "upload" && (
              <div className="field-stack">
                <label htmlFor="ledger-file">Ledger CSV</label>
                <input id="ledger-file" type="file" accept=".csv,text/csv" onChange={selectFile} />
                {props.uploadName && <p className="field-help">Selected: {props.uploadName}</p>}
                {props.uploadPending && <p className="field-help">Reading CSV…</p>}
                {props.uploadError && <p className="field-error" role="alert">{props.uploadError}</p>}
              </div>
            )}
            <label className="check-row"><input type="checkbox" checked={props.overrideDate} onChange={(event) => props.onOverrideDateChange(event.target.checked)} />Override as-of date</label>
            {props.overrideDate && <div className="field-stack"><label htmlFor="as-of-date">As-of date</label><input id="as-of-date" type="date" value={props.asOfDate} onChange={(event) => props.onAsOfDateChange(event.target.value)} /></div>}
          </section>
        )}

        <section className="settings-section">
          <div className="section-heading"><h3>Context</h3><p>Choose how long conversations are compacted before each model request.</p></div>
          <div className="settings-grid">
            <div className="field-stack">
              <label htmlFor="context-mode">Strategy</label>
              <select id="context-mode" disabled={props.disabled} value={props.contextMode} onChange={(event) => props.onContextModeChange(event.target.value as ContextMode)}>
                <option value="auto">Auto</option><option value="jev">Jev</option><option value="summary">Summary</option>
              </select>
            </div>
            <div className="field-stack">
              <label htmlFor="compaction-turns">Compact after turns</label>
              <input id="compaction-turns" disabled={props.disabled} type="number" min={5} max={100} value={props.compactionTurns} onChange={(event) => {
                const value = event.currentTarget.valueAsNumber;
                if (Number.isInteger(value) && value >= 5 && value <= 100) props.onCompactionTurnsChange(value);
              }} />
            </div>
          </div>
        </section>

        <section className="settings-section">
          <div className="section-heading"><h3>Agent execution</h3><p>Limit each answer to a fixed number of model-and-tool steps.</p></div>
          <div className="field-stack">
            <label htmlFor="max-agent-steps">Max agent steps</label>
            <input id="max-agent-steps" disabled={props.disabled} type="number" min={1} max={100} value={props.maxAgentSteps} onChange={(event) => {
              const value = event.currentTarget.valueAsNumber;
              if (Number.isInteger(value) && value >= 1 && value <= 100) props.onMaxAgentStepsChange(value);
            }} />
          </div>
        </section>

        {!active && (
          <section className="settings-section">
            <div className="section-heading"><h3>Budget rules</h3><p>The model compiles plain language; validated code evaluates the ledger.</p></div>
            <div className="field-stack">
              <label htmlFor="budget-rules">Natural-language rules</label>
              <textarea id="budget-rules" rows={7} value={props.rulesText} onChange={(event) => props.onRulesTextChange(event.target.value)} />
            </div>
            <div className="button-row">
              <button className="primary-button" type="button" disabled={props.parsing || props.signaturePending} onClick={props.onParse}>{props.parsing ? "Parsing…" : "Parse rules"}</button>
              <button className="secondary-button" type="button" onClick={props.onReset}>Use defaults</button>
            </div>
            {props.error && <div className="settings-error" role="alert"><MarkdownContent content={props.error} /></div>}
            {props.parsedRules && props.previewCurrent && (
              <div className="rule-preview">
                <h4>Compiled preview</h4>
                <RuleList rules={props.parsedRules} />
                {props.warnings.map((warning) => <div className="settings-warning" key={warning}><MarkdownContent content={warning} /></div>)}
                <details className="tool-disclosure technical-details"><summary>Technical details</summary><pre>{JSON.stringify(props.parsedRules, null, 2)}</pre></details>
                <button className="secondary-button full-width" type="button" onClick={props.onConfirm}>Confirm these rules</button>
              </div>
            )}
            {props.parsedRules && !props.previewCurrent && !props.signaturePending && <p className="settings-warning">The rules or ledger changed. Parse again before confirming.</p>}
            {!props.signaturePending && <p className="settings-note">{props.confirmedCurrent ? "Custom rules are confirmed for the next chat." : "New chats use the built-in rules."}</p>}
          </section>
        )}
      </div>
    </dialog>
  );
}
