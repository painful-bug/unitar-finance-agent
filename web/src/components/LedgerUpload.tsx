import { useRef, useState } from "react";
import type { LedgerMetadata } from "../types";

export interface LedgerUploadProps {
  ledger: LedgerMetadata | null;
  uploadPending: boolean;
  uploadError: string;
  ledgerDisabled: boolean;
  onUpload: (file: File | null) => void;
}

export function LedgerUpload({ ledger, uploadPending, uploadError, ledgerDisabled, onUpload, compact = false }: LedgerUploadProps & { compact?: boolean }) {
  const input = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);
  const disabled = ledgerDisabled || uploadPending;
  const uploaded = ledger?.ledger_source === "upload";
  return <section className={`ledger-upload ${compact ? "is-compact" : ""} ${dragging ? "is-dragging" : ""}`} aria-label="Chat ledger"
    onDragOver={(event) => { event.preventDefault(); if (!disabled) setDragging(true); }}
    onDragLeave={(event) => { if (!event.currentTarget.contains(event.relatedTarget as Node | null)) setDragging(false); }}
    onDrop={(event) => { event.preventDefault(); setDragging(false); if (!disabled && event.dataTransfer.files.length) onUpload(event.dataTransfer.files[0]); }}>
    <input ref={input} className="sr-only" tabIndex={-1} type="file" accept=".csv,text/csv" aria-label="Ledger CSV" disabled={disabled}
      onChange={(event) => { const file = event.target.files?.[0]; if (file) onUpload(file); event.target.value = ""; }} />
    <div className="ledger-upload-main"><span className="ledger-file-icon" aria-hidden="true">▤</span>
      <div className="ledger-upload-copy"><span className="eyebrow">{compact ? "Active ledger" : "Your chat, your data"}</span>
        <h3>{uploaded ? ledger.upload_name ?? "Uploaded CSV" : "Bundled demo ledger"}</h3>
        <p>{ledger ? `${ledger.transaction_count.toLocaleString()} transactions · ${ledger.as_of_date}` : "Ready to explore. No upload needed."}</p>
      </div><span className="ledger-ready"><span className="status-dot" aria-hidden="true" />{uploadPending ? "Validating…" : "Ready"}</span>
    </div>
    <div className="ledger-upload-actions"><button type="button" className={compact ? "secondary-button" : "primary-button"} disabled={disabled} onClick={() => input.current?.click()}>{uploaded || compact ? "Replace CSV" : "Choose CSV"}</button>
      {uploaded && <button type="button" className="secondary-button" disabled={disabled} onClick={() => onUpload(null)}>Use bundled data</button>}
      {!compact && <p>or drop a CSV here <span>· up to 10 MB / 50,000 rows</span></p>}
    </div>
    {!compact && <p className="ledger-columns">Required columns: <code>date</code>, <code>kind</code>, <code>category</code>, <code>amount</code>. <code>merchant</code> is optional.</p>}
    {uploadPending && <p className="field-help" role="status">Reading and validating your CSV…</p>}
    {uploadError && <p className="field-error" role="alert">{uploadError}</p>}
  </section>;
}
