# Finance prompt evaluation report

Verified live run: **October 01, 2026, 00:50:26–00:54:13 IST**. Status: **complete**.

The simplified implementation follows the instructor notebook’s direct prompt comparison: twelve golden questions, five case-insensitive literal keyword checks, seven separate LLM-judge checks, and boolean pass-rate calculation. It ran three fresh repetitions per prompt: **72 answers, 42 LLM judgments, 30 keyword checks, and zero service failures**. No answers or grades were selectively rerun.

| Prompt | Run 1 | Run 2 | Run 3 | Aggregate / mean | Minimum–maximum | Range |
|---|---:|---:|---:|---:|---:|---:|
| Prompt A (baseline) | 10/12 (83.33%) | 12/12 (100.00%) | 11/12 (91.67%) | 33/36 (91.67%) | 83.33%–100.00% | 16.67 pp |
| Prompt B (grounded) | 10/12 (83.33%) | 10/12 (83.33%) | 10/12 (83.33%) | 30/36 (83.33%) | 83.33%–83.33% | 0.00 pp |

Prompt B’s aggregate is **8.33 percentage points lower**. It produced an identical rate in all three observed runs; this does not guarantee future stability or identical wording. Prompt A’s rate varied. These findings do not show an overall accuracy improvement from the grounded prompt.

| Prompt | Keyword checks | LLM-judge checks |
|---|---:|---:|
| Prompt A (baseline) | 15/15 | 18/21 |
| Prompt B (grounded) | 12/15 | 18/21 |

## What failed

- Prompt A, run 1: the responsibility answer made an unqualified overall assessment; the relative-date answer omitted July. The judge failed both against the stated criteria.
- Prompt A, run 3: the judge rejected the combined budget/savings answer, calling RM 1,849.35 inaccurate. **That amount is correct in the reference.** Income RM 5,000 minus expenses RM 3,150.65 is RM 1,849.35; its savings rate rounds to 36.99%. This is a judge error on manual inspection. The recorded failing verdict remains unchanged, demonstrating that model judgments are fallible.
- Prompt B, all three runs: the grocery-budget answer gave both correct amounts but omitted the required literal word `within`. It failed the assigned notebook-style keyword check.
- Prompt B, all three runs: “I don’t know” did not explain that September records were absent. The stated rubric requires that qualification, so the judge failed it.

## Method and interpretation

Prompt A asks a finance assistant to answer using the fixed reference. Prompt B adds the notebook’s rules to answer only from that reference, admit missing information, never invent an answer, and keep the reply to two or three sentences. Each question has its own independent two-message conversation. The answer model never receives judge criteria.

Answer generation uses `openai/gpt-oss-20b`; the separate judge call uses `openai/gpt-oss-120b`. Temperature is 0 for both. The model split and fixed temperature are the approved adaptations to the notebook. Instructor JSON mode validates `AnswerJudgment(passed, score, reasoning)` with `max_retries=2`; scores are bounded 1–5 and do not impose a passing threshold.

The only run argument is `--repeats`, default 3. There are no Jev evaluation calls, workers, Git snapshots, context compaction, Settings lookups, confidence thresholds, custom pacing, resume, or quota recovery. Old settings and chat snapshots discard only the retired evaluation field; the application’s context features remain available.

These results compare **prompts**, not historical application versions or actual tool execution. The synthetic reference gives recorded finance facts explicitly. The old version-comparison results and notebook’s cached example rates are separate evidence. Twelve questions and three runs do not establish general financial accuracy. Literal substring checks and the LLM judge both have limitations, illustrated above.

## Run it again

```bash
uv run --extra eval --env-file .env python tools/run_evaluation.py
```

Add `--repeats 1` for the shorter live demonstration. The console prints every question, answer, literal match or judge criterion, verdict, score, and reasoning. Each execution saves a fresh report and JSON record. Provider failures save incomplete evidence and exit unsuccessfully.

## Evidence and verification

[Full generated report](../evals/results/20260930T192026460536Z/report.md) · [Structured run evidence](../evals/results/20260930T192026460536Z/results.json) · [Operating guide](evaluation-guide.md). The generated run files are retained locally and excluded from Git.

The result audit confirmed six complete runs, twelve unique cases per run, matching saved/current datasets, correctly recomputed aggregate rates, 42 structured judgments, and no execution or judge service errors. Offline verification passed **69 Python tests**, **47 frontend tests**, lint, type checking, and build. The build retains its existing large-bundle warning. CI now installs the evaluation extras for its mocked provider-failure test.

The prior implementation is recoverable from checkpoint commit `a3d9f3f`. This report accompanies the separate simplification commit.
