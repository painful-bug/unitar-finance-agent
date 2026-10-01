# Finance agent evaluation

State: **complete**. One pass per prompt; 12 cases each.

| Prompt | Passed | Pass rate | Keyword | LLM judge | Tool calls |
|---|---:|---:|---:|---:|---:|
| Prompt A (baseline) | 8/12 | 66.67% | 3/5 | 5/7 | 14 |
| Prompt B (grounded) | 12/12 | 100.00% | 5/5 | 7/7 | 14 |

**Result: Prompt B scored higher by 33.33 percentage points.**

| Case | Prompt A | Prompt B |
|---|---|---|
| july_groceries_total | PASS | PASS |
| june_dining_total | PASS | PASS |
| july_dining_over_budget | FAIL | PASS |
| july_groceries_within_budget | FAIL | PASS |
| july_savings_rate | PASS | PASS |
| zero_income | PASS | PASS |
| missing_month | FAIL | PASS |
| ambiguous_request | FAIL | PASS |
| combined_budget_and_savings | PASS | PASS |
| relative_date | PASS | PASS |
| july_dining_transactions | PASS | PASS |
| unsupported_bank_balance | PASS | PASS |

Bundled demo.csv; as-of 2026-08-15. Agent: openai/gpt-oss-20b; judge: openai/gpt-oss-120b; temperature 0.
Same dataset, tools, rules, and settings; only the prompt differs. No reference answers are supplied to the agent.
Higher pass rate means better on this run and rubric; one run does not establish consistent or general superiority. Literal checks and LLM judges can be wrong.
Full prompts, answers, judgments, tool traces, and errors: [results.json](../evals/results/20261001T043928284013Z/results.json).
