export type ContextMode = "auto" | "jev" | "summary";
export type ContextStrategy = "none" | "jev" | "summary";
export type AgentStatus = "ok" | "max_steps" | "error" | "context_error";

export type MetricName =
  | "income"
  | "expenses"
  | "savings"
  | "savings_rate"
  | "transaction_sum"
  | "transaction_count"
  | "transaction_average"
  | "transaction_minimum"
  | "transaction_maximum";

export type Unit = "RM" | "percent" | "count";
export type Operator = "lt" | "lte" | "eq" | "gte" | "gt";
export type TransactionKind = "income" | "expense";
export type DecimalValue = string | number;

export interface Operand {
  metric?: MetricName | null;
  value?: DecimalValue | null;
  unit: Unit;
  multiplier?: DecimalValue;
  kind?: TransactionKind | null;
  category?: string | null;
  merchant?: string | null;
}

export interface BudgetRule {
  rule_id: string;
  source_text: string;
  supported?: boolean;
  left?: Operand | null;
  operator?: Operator | null;
  right?: Operand | null;
  unsupported_reason?: string | null;
}

export interface BudgetRulePreview {
  rules: BudgetRule[];
  warnings?: string[];
}

export interface SessionInfo {
  session_id: string;
  as_of_date: string;
  context_mode: ContextMode;
  transaction_count: number;
  budget_rules: BudgetRule[];
  compaction_turns: number;
  ledger_source: "demo" | "upload";
  upload_name?: string | null;
}

export interface CloseResult {
  session_id: string;
  closed: boolean;
}

export interface TraceEvent {
  step: number;
  tool: string;
  arguments?: Record<string, unknown> | null;
  result?: Record<string, unknown> | null;
  error?: string | null;
}

export interface ContextDecision {
  tool_call_id: string;
  call_probability?: number;
  result_probability?: number;
  action: "keep" | "trim" | "drop";
}

export interface ContextMessage {
  role?: string;
  content?: unknown;
  tool_calls?: Array<{
    id?: string;
    function?: { name?: string; arguments?: string };
  }>;
  tool_call_id?: string;
  [key: string]: unknown;
}

export interface ContextReport {
  strategy?: ContextStrategy;
  before_tokens?: number;
  after_tokens?: number;
  fallback_reason?: string | null;
  decisions?: ContextDecision[];
  before_messages?: ContextMessage[];
  after_messages?: ContextMessage[];
}

export interface AgentResult {
  answer: string;
  status: AgentStatus;
  steps: number;
  trace?: TraceEvent[];
  context?: ContextReport;
}

export interface ChatThreadSummary {
  thread_id: string;
  title: string;
  created_at: string;
  updated_at: string;
  turn_count: number;
  ledger_source: "demo" | "upload";
  upload_name?: string | null;
}

export interface ChatTurn {
  turn_id: string;
  created_at: string;
  question: string;
  state: "pending" | "complete" | "interrupted";
  result?: AgentResult | null;
}

export interface ChatThreadDetail {
  summary: ChatThreadSummary;
  as_of_date: string;
  context_mode: ContextMode;
  transaction_count: number;
  budget_rules: BudgetRule[];
  compaction_turns: number;
  turns: ChatTurn[];
}

export interface ChatThreadList {
  threads: ChatThreadSummary[];
  skipped_files: number;
}

export interface UpdateChatThreadInput {
  thread_id: string;
  title?: string | null;
  context_mode?: ContextMode | null;
  compaction_turns?: number | null;
}

export interface DeleteChatThreadResult {
  thread_id: string;
  deleted: boolean;
}

export interface ParseBudgetRulesInput {
  rules_text: string;
  csv_text?: string | null;
}

export interface CreateFinanceSessionInput {
  csv_text?: string | null;
  upload_name?: string | null;
  as_of_date?: string | null;
  context_mode?: ContextMode;
  budget_rules?: BudgetRule[] | null;
  compaction_turns?: number;
}

export interface AskFinanceAgentInput {
  session_id: string;
  question: string;
  context_mode?: ContextMode | null;
  include_context?: boolean;
  compaction_turns?: number | null;
}

export interface CloseFinanceSessionInput {
  session_id: string;
}
