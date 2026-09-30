import { MarkdownContent } from "./MarkdownContent";
import type { TraceEvent } from "../types";


function object(value: unknown): Record<string, unknown> | null {
  return typeof value === "object" && value !== null && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

function text(value: unknown, fallback = "—"): string {
  if (value === null || value === undefined || value === "") return fallback;
  return typeof value === "object" ? JSON.stringify(value) : String(value);
}

function money(value: unknown): string {
  return value === null || value === undefined ? "—" : `RM ${String(value)}`;
}

function measure(value: unknown, unit: unknown): string {
  if (value === null || value === undefined) return "—";
  if (unit === "percent") return `${String(value)}%`;
  if (unit === "count") return String(value);
  return money(value);
}

function evidence(result: Record<string, unknown>): string {
  if (typeof result.reason === "string" && result.reason) return result.reason;
  const values = object(result.evidence);
  const counts = [object(values?.left), object(values?.right)]
    .map((item) => item?.matched_transactions)
    .filter((value): value is number => typeof value === "number");
  if (!counts.length) return "Validated from the active ledger.";
  const matched = Math.max(...counts);
  return `${matched} matching ledger ${matched === 1 ? "entry" : "entries"}.`;
}

function month(value: unknown): string {
  if (typeof value !== "string" || !/^\d{4}-\d{2}$/.test(value)) return text(value);
  const [year, number] = value.split("-").map(Number);
  return new Intl.DateTimeFormat(undefined, { month: "short", year: "numeric" }).format(
    new Date(year, number - 1, 1),
  );
}

function humanize(value: string): string {
  const label = value.replaceAll("_", " ");
  return label.charAt(0).toUpperCase() + label.slice(1);
}

function Metrics({ values }: { values: Array<[string, string]> }) {
  return (
    <dl className="tool-metrics">
      {values.map(([label, value]) => (
        <div key={label}>
          <dt>{label}</dt>
          <dd>{value}</dd>
        </div>
      ))}
    </dl>
  );
}

function LookupDetails({ result }: { result: Record<string, unknown> }) {
  const transactions = Array.isArray(result.transactions) ? result.transactions : [];
  if (!transactions.length) return null;
  return (
    <details className="tool-disclosure">
      <summary>View transactions</summary>
      <div className="table-scroll">
        <table>
          <thead>
            <tr><th>Date</th><th>Category</th><th>Merchant</th><th>Kind</th><th>Amount</th></tr>
          </thead>
          <tbody>
            {transactions.map((item, index) => {
              const row = object(item) ?? {};
              return (
                <tr key={`${text(row.date)}-${index}`}>
                  <td>{text(row.date)}</td>
                  <td>{text(row.category)}</td>
                  <td>{text(row.merchant)}</td>
                  <td>{text(row.kind)}</td>
                  <td>{money(row.amount)}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </details>
  );
}

export function ToolActivity({ event }: { event: TraceEvent }) {
  const args = event.arguments ?? {};
  const result = event.result ?? {};
  const failed = Boolean(event.error);
  let title = humanize(event.tool || "tool activity");
  let description = `Completed step ${event.step}.`;
  let details = <Metrics values={Object.entries(result).slice(0, 6).map(([key, value]) => [humanize(key), text(value)])} />;

  if (event.tool === "lookup_transactions") {
    const subject = text(args.category ?? args.kind, "ledger");
    title = `Looked up ${subject} transactions`;
    description = `Reviewed ${month(args.month)} ledger entries.`;
    details = (
      <>
        <Metrics values={[["Transactions", text(result.count, "0")], ["Total", money(result.total)]]} />
        <LookupDetails result={result} />
      </>
    );
  } else if (event.tool === "calculate_savings_rate") {
    title = "Calculated savings rate";
    description = `Calculated from the ${month(args.month)} ledger.`;
    details = (
      <Metrics values={[
        ["Income", money(result.income)],
        ["Expenses", money(result.expenses)],
        ["Savings", money(result.savings)],
        ["Rate", result.rate == null ? "Unavailable" : `${String(result.rate)}%`],
      ]} />
    );
  } else if (event.tool === "check_budget_rule") {
    const rule = text(result.source_text ?? args.rule_id, "budget rule");
    title = `Checked ${rule} for ${month(args.month)}`;
    description = evidence(result);
    details = (
      <Metrics values={[
        ["Status", humanize(text(result.status, "unknown"))],
        ["Observed", measure(result.observed, result.unit)],
        ["Limit", measure(result.limit, result.unit)],
        ["Unit", text(result.unit)],
      ]} />
    );
  }

  if (failed) {
    title = `${humanize(event.tool)} failed`;
    description = event.error ?? "The tool could not complete.";
    details = <></>;
  }

  return (
    <article className={`tool-activity ${failed ? "is-error" : ""}`}>
      <div className="tool-heading">
        <span className="status-dot" aria-hidden="true" />
        <div>
          <h4>{title}</h4>
          {failed ? <MarkdownContent content={description} /> : <p>{description}</p>}
        </div>
      </div>
      {details}
      <details className="tool-disclosure technical-details">
        <summary>Technical details</summary>
        <pre>{JSON.stringify({ arguments: event.arguments ?? null, result: event.result ?? null, error: event.error ?? null }, null, 2)}</pre>
      </details>
    </article>
  );
}
