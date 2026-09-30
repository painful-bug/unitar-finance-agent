# Graph Report - .  (2026-09-30)

## Corpus Check
- Corpus is ~38,224 words - fits in a single context window. You may not need a graph.

## Summary
- 532 nodes · 1660 edges · 32 communities (26 shown, 6 thin omitted)
- Extraction: 64% EXTRACTED · 36% INFERRED · 0% AMBIGUOUS · INFERRED: 601 edges (avg confidence: 0.51)
- Token cost: 0 input · 0 output

## Community Hubs (Navigation)
- [[_COMMUNITY_Chat Sessions|Chat Sessions]]
- [[_COMMUNITY_Budget Rules|Budget Rules]]
- [[_COMMUNITY_Agent Loop|Agent Loop]]
- [[_COMMUNITY_Web Dependencies|Web Dependencies]]
- [[_COMMUNITY_Context Management|Context Management]]
- [[_COMMUNITY_Context UI|Context UI]]
- [[_COMMUNITY_Evaluation|Evaluation]]
- [[_COMMUNITY_Preferences|Preferences]]
- [[_COMMUNITY_React App|React App]]
- [[_COMMUNITY_Deployment|Deployment]]
- [[_COMMUNITY_Data Models|Data Models]]
- [[_COMMUNITY_MCP Client|MCP Client]]
- [[_COMMUNITY_TypeScript Config|TypeScript Config]]
- [[_COMMUNITY_Client Transport|Client Transport]]
- [[_COMMUNITY_Chat Components|Chat Components]]
- [[_COMMUNITY_Thread Tests|Thread Tests]]
- [[_COMMUNITY_Thread Sidebar|Thread Sidebar]]
- [[_COMMUNITY_Chat Persistence|Chat Persistence]]
- [[_COMMUNITY_Compaction Demo|Compaction Demo]]
- [[_COMMUNITY_Docker Script|Docker Script]]
- [[_COMMUNITY_Design System|Design System]]
- [[_COMMUNITY_Dev Script|Dev Script]]
- [[_COMMUNITY_Budget Workflow|Budget Workflow]]
- [[_COMMUNITY_Vite Config|Vite Config]]
- [[_COMMUNITY_Demo Data|Demo Data]]
- [[_COMMUNITY_Package Metadata|Package Metadata]]
- [[_COMMUNITY_Migration Risks|Migration Risks]]
- [[_COMMUNITY_Project Metadata|Project Metadata]]

## God Nodes (most connected - your core abstractions)
1. `FinanceData` - 57 edges
2. `Session` - 56 edges
3. `GroqProvider` - 54 edges
4. `ContextManager` - 54 edges
5. `BudgetRule` - 50 edges
6. `ContextReport` - 47 edges
7. `AgentResult` - 47 edges
8. `ChatProvider` - 39 edges
9. `SessionStore` - 36 edges
10. `ContextManagementError` - 33 edges

## Surprising Connections (you probably didn't know these)
- `Jev Context Compaction Demo` --semantically_similar_to--> `Jev Context Compaction`  [INFERRED] [semantically similar]
  docs/context-compaction-demo.md → README.md
- `ChatStore` --semantically_similar_to--> `Chat Thread JSON Records`  [INFERRED] [semantically similar]
  docs/chat-thread-persistence.md → README.md
- `Rule Workflow State Machine` --semantically_similar_to--> `Natural Language Budget Rules`  [INFERRED] [semantically similar]
  docs/migration/04-phases-and-testing.md → README.md
- `Decimal Display Boundary` --semantically_similar_to--> `Decimal Budget Evaluation`  [INFERRED] [semantically similar]
  docs/migration/02-api-contract.md → README.md
- `React Browser MCP Client` --semantically_similar_to--> `React UI`  [INFERRED] [semantically similar]
  docs/migration/01-target-architecture.md → README.md

## Import Cycles
- 1-file cycle: `src/finance_agent/agent.py -> src/finance_agent/agent.py`
- 1-file cycle: `src/finance_agent/budget.py -> src/finance_agent/budget.py`
- 1-file cycle: `src/finance_agent/finance.py -> src/finance_agent/finance.py`
- 1-file cycle: `src/finance_agent/threads.py -> src/finance_agent/threads.py`
- 2-file cycle: `src/finance_agent/models.py -> src/finance_agent/threads.py -> src/finance_agent/models.py`
- 3-file cycle: `src/finance_agent/finance.py -> src/finance_agent/threads.py -> src/finance_agent/models.py -> src/finance_agent/finance.py`

## Hyperedges (group relationships)
- **Local React MCP Architecture** — readme_react_ui, readme_mcp_server, readme_same_origin_mcp_proxy, migration_01_target_architecture_react_browser_mcp_client, migration_01_target_architecture_nginx_same_origin_proxy [EXTRACTED 1.00]
- **Durable Chat Thread Lifecycle** — readme_saved_chat_threads, readme_chat_thread_json_records, docs_chat_thread_persistence_chatstore, docs_chat_thread_persistence_pending_turn_recovery, docs_chat_thread_persistence_browser_history_routes [EXTRACTED 1.00]
- **Context Compaction Audit Flow** — readme_context_modes, readme_jev_context_compaction, readme_turn_based_compaction_threshold, docs_context_compaction_demo_deterministic_5000_row_fixture, docs_context_compaction_demo_context_inspector_audit_receipt [EXTRACTED 1.00]

## Communities (32 total, 6 thin omitted)

### Community 0 - "Chat Sessions"
Cohesion: 0.17
Nodes (38): BudgetRulePreview, ChatStore, ChatThreadDetail, ChatThreadList, CompactionTurns, ContextMode, DeleteChatThreadResult, ChatProvider (+30 more)

### Community 1 - "Budget Rules"
Cohesion: 0.08
Nodes (39): BudgetResult, BudgetResult, BudgetRuleSet, _canonical_rule_id(), default_budget_rules(), _normalize_ids(), Operand, parse_budget_rules() (+31 more)

### Community 2 - "Agent Loop"
Cohesion: 0.21
Nodes (29): BaseModel, _assistant_message(), AssistantTurn, BudgetArgs, _execute_tool(), _groq_schema(), LookupArgs, _run_agent() (+21 more)

### Community 3 - "Web Dependencies"
Cohesion: 0.05
Nodes (39): dependencies, @fontsource/inconsolata, @fontsource/inter, @fontsource/open-sans, @modelcontextprotocol/client, react, react-dom, react-markdown (+31 more)

### Community 4 - "Context Management"
Cohesion: 0.13
Nodes (23): ContextReport, _apply_decisions(), estimate_tokens(), _excerpt(), _jev_state(), JevJudge, _questions(), _safe_prefix_cut() (+15 more)

### Community 5 - "Context UI"
Cohesion: 0.11
Nodes (22): actionFor(), contentText(), ContextPanel(), ContextPanelProps, ContextTab, MessageCard(), context, CodeBlock() (+14 more)

### Community 6 - "Evaluation"
Cohesion: 0.17
Nodes (24): ContextManager, deterministic_check(), _judge(), JudgeVerdict, main(), run_evaluation(), GroqProvider, RuntimeError (+16 more)

### Community 7 - "Preferences"
Cohesion: 0.13
Nodes (21): DEFAULT_PREFERENCES, DEFAULT_RULES_TEXT, defaultRulePreferences(), isBudgetRule(), isObject(), loadCompactionTurns(), loadRulePreferences(), loadTheme() (+13 more)

### Community 8 - "React App"
Cohesion: 0.11
Nodes (18): detail(), result, summary(), AgentResult, AgentStatus, AskFinanceAgentInput, ChatTurn, CloseFinanceSessionInput (+10 more)

### Community 9 - "Deployment"
Cohesion: 0.09
Nodes (23): Finance Chat Data Volume, Finance MCP Compose Service, React UI Compose Service, Complete Response Delivery, Nginx Same Origin Proxy, React Browser MCP Client, MCP API Contract, Same Origin MCP Transport (+15 more)

### Community 10 - "Data Models"
Cohesion: 0.21
Nodes (13): AssistantTurn, datetime, _require_utc(), FakeProvider, session(), test_agent_executes_validated_tool_then_returns_answer(), test_agent_stops_at_hard_step_limit(), test_empty_final_turn_is_an_error_and_is_not_saved() (+5 more)

### Community 11 - "MCP Client"
Cohesion: 0.15
Nodes (15): AdapterFactory, EXPECTED_TOOLS, isAgentResult(), isBudgetRulePreview(), isChatThreadDetail(), isChatThreadList(), isCloseResult(), isDeleteChatThreadResult() (+7 more)

### Community 12 - "TypeScript Config"
Cohesion: 0.11
Nodes (18): compilerOptions, allowJs, allowSyntheticDefaultImports, esModuleInterop, forceConsistentCasingInFileNames, isolatedModules, jsx, lib (+10 more)

### Community 13 - "Client Transport"
Cohesion: 0.17
Nodes (8): clientError(), FinanceMcpClient, textContent(), BudgetRulePreview, ChatThreadList, DeleteChatThreadResult, ParseBudgetRulesInput, UpdateChatThreadInput

### Community 14 - "Chat Components"
Cohesion: 0.21
Nodes (9): ChatPanel(), ChatPanelProps, comparison(), LedgerSource, operandValue(), SettingsPanel(), SettingsPanelProps, ChatThreadDetail (+1 more)

### Community 15 - "Thread Tests"
Cohesion: 0.44
Nodes (8): Path, run(), test_chat_title_is_deterministic_and_bounded(), test_failed_thread_update_rolls_back_in_memory_state(), test_pending_turn_is_recovered_as_interrupted(), test_store_permissions_validation_and_corrupt_file_isolation(), test_uploaded_thread_survives_restart_without_exposing_csv(), ThreadProvider

### Community 16 - "Thread Sidebar"
Cohesion: 0.31
Nodes (8): ConnectionStatus, dayStart(), groupThreads(), ThreadGroup, ThreadSidebar(), ThreadSidebarProps, Theme, ChatThreadSummary

### Community 17 - "Chat Persistence"
Cohesion: 0.25
Nodes (8): Browser History Chat Routes, ChatThreadDetail, ChatStore, Durable Chat Threads, Pending Turn Recovery, State Ownership, Chat Thread JSON Records, Saved Chat Threads

### Community 18 - "Compaction Demo"
Cohesion: 0.29
Nodes (7): Context Inspector Audit Receipt, Deterministic 5000 Row Fixture, Jev Context Compaction Demo, Context Modes, Groq Summary Fallback, Jev Context Compaction, Turn Based Compaction Threshold

### Community 19 - "Docker Script"
Cohesion: 0.60
Nodes (3): fail(), probe_mcp(), dev_docker.sh script

### Community 20 - "Design System"
Cohesion: 0.40
Nodes (5): Accessible Native Controls, Achromatic Interface, Double Ring Focus Pattern, Shadow As Border, Vercel Design Language

### Community 22 - "Budget Workflow"
Cohesion: 0.50
Nodes (4): Decimal Display Boundary, Rule Workflow State Machine, Decimal Budget Evaluation, Natural Language Budget Rules

## Knowledge Gaps
- **101 isolated node(s):** `finance-agent-beta`, `Any`, `SystemOneResponse`, `name`, `private` (+96 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **6 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `ContextManager` connect `Evaluation` to `Chat Sessions`, `Budget Rules`, `Agent Loop`, `Context Management`, `Thread Tests`?**
  _High betweenness centrality (0.031) - this node is a cross-community bridge._
- **Why does `FinanceData` connect `Chat Sessions` to `Budget Rules`, `Data Models`, `Agent Loop`, `Evaluation`?**
  _High betweenness centrality (0.030) - this node is a cross-community bridge._
- **Why does `JevClient` connect `Context Management` to `Evaluation`?**
  _High betweenness centrality (0.021) - this node is a cross-community bridge._
- **Are the 38 inferred relationships involving `FinanceData` (e.g. with `AssistantTurn` and `BudgetRulePreview`) actually correct?**
  _`FinanceData` has 38 INFERRED edges - model-reasoned connections that need verification._
- **Are the 50 inferred relationships involving `Session` (e.g. with `AssistantTurn` and `BudgetRulePreview`) actually correct?**
  _`Session` has 50 INFERRED edges - model-reasoned connections that need verification._
- **Are the 41 inferred relationships involving `GroqProvider` (e.g. with `AssistantTurn` and `BudgetRulePreview`) actually correct?**
  _`GroqProvider` has 41 INFERRED edges - model-reasoned connections that need verification._
- **Are the 37 inferred relationships involving `ContextManager` (e.g. with `BudgetRulePreview` and `ChatStore`) actually correct?**
  _`ContextManager` has 37 INFERRED edges - model-reasoned connections that need verification._