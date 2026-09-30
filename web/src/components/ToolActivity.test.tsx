import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { ToolActivity } from "./ToolActivity";


afterEach(cleanup);

describe("ToolActivity", () => {
  it("renders a budget result as readable metrics with evidence", () => {
    render(<ToolActivity event={{
      step: 1,
      tool: "check_budget_rule",
      arguments: { month: "2026-08", rule_id: "dining_cap" },
      result: {
        source_text: "Keep dining below RM 500",
        status: "within",
        observed: "420.00",
        limit: "500.00",
        unit: "RM",
        evidence: { left: { matched_transactions: 3 } },
      },
    }} />);

    expect(screen.getByRole("heading", { name: "Checked Keep dining below RM 500 for Aug 2026" })).toBeInTheDocument();
    expect(screen.getByText("3 matching ledger entries.")).toBeInTheDocument();
    expect(screen.getByText("RM 420.00")).toBeInTheDocument();
  });

  it("humanizes unknown tools and keeps raw data collapsed", () => {
    render(<ToolActivity event={{ step: 2, tool: "forecast_balance", arguments: { months: 3 }, result: { confidence: "high" } }} />);

    expect(screen.getByRole("heading", { name: "Forecast balance" })).toBeInTheDocument();
    expect(screen.getByText("Confidence")).toBeInTheDocument();
    expect(screen.getByText("Technical details").closest("details")).not.toHaveAttribute("open");
  });

  it("shows tool failures as readable errors", () => {
    render(<ToolActivity event={{ step: 3, tool: "lookup_transactions", error: "The ledger is unavailable." }} />);

    expect(screen.getByRole("heading", { name: "Lookup transactions failed" })).toBeInTheDocument();
    expect(screen.getByText("The ledger is unavailable.")).toBeInTheDocument();
  });
});
