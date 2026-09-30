import { beforeEach, describe, expect, it } from "vitest";

import type { BudgetRule } from "../types";
import {
  DEFAULT_RULES_TEXT,
  COMPACTION_TURNS_KEY,
  DEFAULT_COMPACTION_TURNS,
  RULE_EDITOR_VERSION,
  RULE_PREFERENCES_KEY,
  THEME_KEY,
  defaultRulePreferences,
  loadRulePreferences,
  loadCompactionTurns,
  loadTheme,
  rulesSignature,
  saveRulePreferences,
  saveCompactionTurns,
  saveTheme,
} from "./preferences";

const RULE: BudgetRule = {
  rule_id: "minimum_savings_rate",
  source_text: "Save at least 25% of monthly income.",
  supported: true,
  left: {
    metric: "savings_rate",
    value: null,
    unit: "percent",
    multiplier: "1",
    kind: null,
    category: null,
    merchant: null,
  },
  operator: "gte",
  right: {
    metric: null,
    value: "25",
    unit: "percent",
    multiplier: "1",
    kind: null,
    category: null,
    merchant: null,
  },
  unsupported_reason: null,
};

beforeEach(() => localStorage.clear());

describe("rule preferences", () => {
  it("uses the exact three default rule sentences", () => {
    expect(DEFAULT_RULES_TEXT).toBe(
      "Keep monthly dining expenses at or below RM500., Keep monthly groceries expenses at or below RM800., Save at least 20% of monthly income.",
    );
  });

  it("matches the existing ledger NUL rules SHA-256 signature", async () => {
    await expect(rulesSignature(new TextEncoder().encode("demo"), DEFAULT_RULES_TEXT)).resolves.toBe(
      "7fb060ee01ec43de38c38ece87ad691249f484e8f816551c4ed77510220754ca",
    );
  });

  it("round-trips a complete confirmed preference record", () => {
    const preferences = {
      version: RULE_EDITOR_VERSION,
      rulesText: RULE.source_text,
      confirmedRules: [RULE],
      confirmedSignature: "signature",
    };

    saveRulePreferences(preferences);

    expect(loadRulePreferences()).toEqual(preferences);
  });

  it("rejects incompatible or incomplete stored records", () => {
    localStorage.setItem(
      RULE_PREFERENCES_KEY,
      JSON.stringify({ version: 0, rulesText: "old", confirmedRules: null }),
    );

    expect(loadRulePreferences()).toEqual(defaultRulePreferences());
  });

  it("keeps storage failures non-fatal", () => {
    const broken = {
      getItem: () => {
        throw new Error("blocked");
      },
      setItem: () => {
        throw new Error("blocked");
      },
    } as unknown as Storage;

    expect(loadRulePreferences(broken)).toEqual(defaultRulePreferences());
    expect(() => saveRulePreferences(defaultRulePreferences(), broken)).not.toThrow();
  });
});

describe("interface preferences", () => {
  it("persists a valid compaction threshold and rejects invalid stored values", () => {
    expect(loadCompactionTurns()).toBe(DEFAULT_COMPACTION_TURNS);
    saveCompactionTurns(5);
    expect(loadCompactionTurns()).toBe(5);

    for (const invalid of [4, 101, 5.5, "5"]) {
      localStorage.setItem(COMPACTION_TURNS_KEY, JSON.stringify(invalid));
      expect(loadCompactionTurns()).toBe(DEFAULT_COMPACTION_TURNS);
    }
  });

  it("uses the system theme until the user saves an explicit choice", () => {
    expect(loadTheme(undefined, true)).toBe("dark");
    expect(loadTheme(undefined, false)).toBe("light");

    saveTheme("dark");
    expect(localStorage.getItem(THEME_KEY)).toBe("dark");
    expect(loadTheme(undefined, false)).toBe("dark");
  });
});
