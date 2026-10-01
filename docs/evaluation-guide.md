# Run the finance agent evaluation

```bash
uv sync --extra eval --extra dev
uv run --extra eval --env-file .env python tools/run_evaluation.py
```

Put `GROQ_API_KEY` in `.env`. Each execution evaluates every golden case **once per prompt**: 24 agent answers, ten keyword checks, and fourteen separate LLM-judge calls, before provider/schema retries. There is no repeat option or Jev evaluation.

The instructor notebook supplies the method: `get_answer`, `check_keywords`, `AnswerJudgment`, `judge_answer`, and `run_eval`. Answers now come from the existing finance agent loop, with all three finance tools available. It uses the same bundled `finance_agent.data/demo.csv` as the application; no custom ledger or reference answers are embedded in the evaluator or sent to the answering model.

Both prompts follow the common production tool instruction and receive these rules:

- Keep monthly dining expenses at or below RM500.
- Keep monthly groceries expenses at or below RM800.
- Save at least 20% of monthly income.

Prompt A is a brief, general finance instruction. Prompt B adds operational guidance: correct month formats, tool choice, budget status and evidence, complete answers to multi-part questions, handling missing income/data, and qualifying broad judgments. It contains no expected transaction totals or grading criteria. Improve prompts before running; retain measured failures afterward.

Every case starts a fresh session anchored to August 15, 2026. Financial results come from `lookup_transactions`, `check_budget_rule`, and `calculate_savings_rate`, using existing validated arguments and deterministic finance code. The agent has up to fifteen model steps; actual tool calls and validation errors are printed and saved. Model steps vary, so total API calls can exceed 24 agent requests plus fourteen judge calls.

The agent uses `openai/gpt-oss-20b`; the independent judge uses `openai/gpt-oss-120b`. Both use temperature 0. Five cases use case-insensitive literal substring checks; seven send only the question, final answer, and written criteria to the judge. Instructor JSON mode validates `passed`, `score` (1–5), and `reasoning`. The boolean verdict determines passing; the score is descriptive.

The twelve cases in `evals/golden.json` match the bundled CSV. The former custom zero-income example now asks about May, which has no recorded income or transactions. The former injected merchant case now checks the real July dining transactions; this dataset does **not** test merchant prompt injection.

The terminal shows questions, model steps, readable tool arguments/results, answers, checks, verdicts, and scores. Each execution writes a short `report.md` with a winner/tie statement, pass rates, and a twelve-row comparison, plus complete evidence in `results.json`, under a fresh timestamped `evals/results/` directory.

Higher pass rate means better on these cases in this run. It does not establish general superiority or stability. Literal checks can reject equivalent wording or accept misleading substrings, and judges can be wrong. A provider error or unfinished agent response marks the comparison incomplete and prevents a winner claim. Partial evidence is saved; a fresh execution is required after resolving the provider problem.

The evaluator does not use app Settings, UI/MCP transport, persisted chats, or context compaction. Earlier plain-LLM and multi-run evaluations remain separate historical evidence.

```bash
uv run --extra dev --extra eval pytest
```
