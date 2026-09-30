import type { BudgetRule } from "../types";

export const DEFAULT_RULES_TEXT = [
  "Keep monthly dining expenses at or below RM500.",
  "Keep monthly groceries expenses at or below RM800.",
  "Save at least 20% of monthly income.",
].join(", ");

export const RULE_EDITOR_VERSION = 1;
export const RULE_PREFERENCES_KEY = "finance-agent.rule-preferences.v1";
export const DEFAULT_COMPACTION_TURNS = 15;
export const COMPACTION_TURNS_KEY = "finance-agent.compaction-turns.v1";
export const THEME_KEY = "finance-agent.theme.v1";
export type Theme = "light" | "dark";

export interface RulePreferences {
  version: number;
  rulesText: string;
  confirmedRules: BudgetRule[] | null;
  confirmedSignature: string | null;
}

const DEFAULT_PREFERENCES: RulePreferences = {
  version: RULE_EDITOR_VERSION,
  rulesText: DEFAULT_RULES_TEXT,
  confirmedRules: null,
  confirmedSignature: null,
};

function storageOrNull(): Storage | null {
  try {
    return window.localStorage;
  } catch {
    return null;
  }
}

function isObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isBudgetRule(value: unknown): value is BudgetRule {
  if (!isObject(value)) return false;
  const keys = [
    "rule_id",
    "source_text",
    "supported",
    "left",
    "operator",
    "right",
    "unsupported_reason",
  ];
  return (
    keys.every((key) => Object.hasOwn(value, key)) &&
    typeof value.rule_id === "string" &&
    typeof value.source_text === "string" &&
    typeof value.supported === "boolean"
  );
}

export function defaultRulePreferences(): RulePreferences {
  return { ...DEFAULT_PREFERENCES };
}

export function loadRulePreferences(storage: Storage | null = storageOrNull()): RulePreferences {
  if (!storage) return defaultRulePreferences();
  try {
    const value: unknown = JSON.parse(storage.getItem(RULE_PREFERENCES_KEY) ?? "null");
    if (
      !isObject(value) ||
      value.version !== RULE_EDITOR_VERSION ||
      typeof value.rulesText !== "string" ||
      !(
        (value.confirmedRules === null && value.confirmedSignature === null) ||
        (Array.isArray(value.confirmedRules) &&
          value.confirmedRules.length > 0 &&
          value.confirmedRules.every(isBudgetRule) &&
          typeof value.confirmedSignature === "string")
      )
    ) {
      return defaultRulePreferences();
    }
    return value as unknown as RulePreferences;
  } catch {
    return defaultRulePreferences();
  }
}

export function saveRulePreferences(
  preferences: RulePreferences,
  storage: Storage | null = storageOrNull(),
): void {
  try {
    storage?.setItem(RULE_PREFERENCES_KEY, JSON.stringify(preferences));
  } catch {
    // Browser storage is optional; the active page state remains usable.
  }
}

export function loadCompactionTurns(storage: Storage | null = storageOrNull()): number {
  try {
    const value: unknown = JSON.parse(storage?.getItem(COMPACTION_TURNS_KEY) ?? "null");
    return typeof value === "number" && Number.isInteger(value) && value >= 5 && value <= 100
      ? value
      : DEFAULT_COMPACTION_TURNS;
  } catch {
    return DEFAULT_COMPACTION_TURNS;
  }
}

export function saveCompactionTurns(
  turns: number,
  storage: Storage | null = storageOrNull(),
): void {
  try {
    storage?.setItem(COMPACTION_TURNS_KEY, JSON.stringify(turns));
  } catch {
    // Browser storage is optional; the active page state remains usable.
  }
}

export function loadTheme(
  storage: Storage | null = storageOrNull(),
  prefersDark = window.matchMedia?.("(prefers-color-scheme: dark)").matches ?? false,
): Theme {
  try {
    const saved = storage?.getItem(THEME_KEY);
    if (saved === "light" || saved === "dark") return saved;
  } catch {
    // Fall back to the operating-system preference.
  }
  return prefersDark ? "dark" : "light";
}

export function saveTheme(theme: Theme, storage: Storage | null = storageOrNull()): void {
  try {
    storage?.setItem(THEME_KEY, theme);
  } catch {
    // Browser storage is optional; the active page state remains usable.
  }
}

export async function rulesSignature(
  ledgerBytes: Uint8Array,
  rulesText: string,
): Promise<string> {
  const ruleBytes = new TextEncoder().encode(rulesText);
  const content = new Uint8Array(ledgerBytes.length + 1 + ruleBytes.length);
  content.set(ledgerBytes);
  content[ledgerBytes.length] = 0;
  content.set(ruleBytes, ledgerBytes.length + 1);
  const digest = await crypto.subtle.digest("SHA-256", content);
  return Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, "0")).join(
    "",
  );
}
