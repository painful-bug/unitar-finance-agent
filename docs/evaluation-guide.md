# Run and present the finance evaluation

Class reference: `starter_g.ipynb`, supplied by the user. SHA-256: `44cc76cf7b252a78ff7cdf596707572b50cb6011556ae1410635278d1c954413`. Its stated exercise behavior is followed, with the user-approved case-insensitive matching and bounded scores; its cells are reference material, not commands to execute.

This is the class notebook's evaluation method applied to the actual finance agent. Twelve frozen synthetic cases live in `evals/golden.json`: five literal, case-insensitive keyword checks and seven model-judged checks. Each case has exactly one assigned check. The normal judge uses the notebook's OpenAI-compatible Groq client, Instructor JSON mode, `AnswerJudgment(passed, score, reasoning)`, and `max_retries=2`. Scores are validated from 1 to 5; the boolean verdict directly determines passing.

Jev runs independently using Choice for pass/fail and Score with five descriptive levels in a single request. Its displayed integer is the most probable native level plus one; ties select the lower level. The native expected score, probabilities, confidence, model, and usage are saved. Jev supplies no generated explanation: the console's **Code-generated summary** is assembled by Python. References: [Choice](https://docs.typesafe.ai/primitives/choice), [Score](https://docs.typesafe.ai/primitives/score).

## Setup

Run from the repository directory, with Python 3.12 or 3.13 and `uv` installed:

```bash
cd /Users/aishik/Developer/unitar-agent-work
uv sync --extra eval --extra dev
```

The existing `.env` must contain `GROQ_API_KEY` and `TYPESAFE_API_KEY` to run both judges. Keys are read from the environment and are not written to evaluation artifacts. Defaults are `openai/gpt-oss-20b` for the agent, `openai/gpt-oss-120b` for the normal judge, and pinned `jev-1.13.0` for the Jev judge. `GROQ_MODEL` and `GROQ_JUDGE_MODEL` can override the Groq model names; the run records them. The final agent's context compaction uses its normal Auto strategy, independently of which evaluation judge is selected.

## Live demo

One paired repetition runs all twelve cases on both versions. To show both judges grading the exact same answers independently:

```bash
uv run --extra eval --env-file .env python tools/run_evaluation.py --judge both
```

To demonstrate each judge individually:

```bash
uv run --extra eval --env-file .env python tools/run_evaluation.py --judge llm
uv run --extra eval --env-file .env python tools/run_evaluation.py --judge jev
```

Those two commands generate separate live answer corpora, so use `--judge both` when comparing judges on identical answers.

To use **Settings → Evaluation → Evaluation judge**:

```bash
uv run --extra eval --env-file .env python tools/run_evaluation.py
```

The script reads the running MCP backend at `http://127.0.0.1:8000/mcp` (or `MCP_PORT`) first. If it is unavailable, it reads the host's persisted settings and labels that source. For a Docker backend or a different port, use `--mcp-url http://127.0.0.1:PORT/mcp`; an explicit unavailable URL fails instead of silently switching stores. `--judge` always overrides Settings. Settings controls only the script, and does not automatically score ordinary chat replies.

Auto uses Jev first. It falls back to the LLM on a service/validation error or confidence below 0.65 on either Jev decision. A confident failing answer remains failed. Forced `jev` never calls the LLM, even at low confidence; forced `llm` never calls Jev for grading. Final-agent context management may itself use Jev regardless of grading mode. The Auto threshold is provisional, not a calibrated accuracy guarantee.

The full suite includes a sixteen-turn memory case, so it makes more than 24 model calls. Allow time for provider quotas; this is a live evaluation, not prerecorded playback. Groq token pacing and bounded retries are shared by both versions and the normal LLM judge, and visibly logged, using the provider's response headers. A daily quota or persistent service failure remains a reported execution failure. Higher account quotas can reduce pauses without changing the harness. See [Groq rate-limit headers](https://console.groq.com/docs/rate-limits).

## What to explain while it runs

1. Show `evals/golden.json`: each keyword case has `must_include`; each judge case has written `criteria` with reference facts. Show the independently verified CSV and Decimal totals printed at startup.
2. Show the two judge controls. A known correct answer must pass, and a deliberately wrong answer must fail. Controls are excluded from the reported denominator. If a control fails, the run stops with its evidence saved.
3. Watch the paired agent executions: the frozen source path identifies the real historical baseline or final workspace snapshot. The console prints the prompt, actual tool arguments/results, answer, status, and model/context progress. Long-case turns are all visible.
4. Watch the grading phase: keyword cases show every literal match and make no judge call. Judge cases show criteria, verdict, score, and explanation or Jev's labeled code summary plus raw probabilities. Both judges reuse the saved answers.
5. Open the path printed at completion: `report.md` shows first/final rates, per-repeat and check-type breakdowns, failures, case changes, and judge disagreements. `results.json` is the audit record; `transcript.txt` is the readable execution log.

A keyword match is deliberately literal, as in class. For example, `450` also occurs inside `14500`, and matching `over` does not detect negation. Those limitations are disclosed; do not describe it as a numeric correctness oracle. The independent Decimal verification checks the frozen reference facts before execution, not the wording of every answer. Judges can also make mistakes; inspect disagreements instead of manually overriding verdicts.

## Official report and checkpoint recovery

The requested official run is three paired repetitions, 36 cases per version per judge:

```bash
uv run --extra eval --env-file .env python tools/run_evaluation.py --judge both --repeats 3
```

The implementation also preserves the earlier quota-affected smoke run in `evals/results/live-smoke/`; it is diagnostic evidence, not the official three-repeat comparison.

Every run creates a fresh directory under `evals/results/`. `--output PATH` chooses a new directory explicitly and refuses to overwrite one. Agent versions are frozen before calls: baseline is the actual `v0.1-baseline` commit; final includes completed uncommitted workspace source files. Both use the same installed dependency runtime; historical dependency versions are not recreated. Native step limits and context behavior are preserved and disclosed. The date is fixed at August 15, 2026; configured chat budget rules and uploaded private ledgers do not enter this synthetic benchmark.

If a completed run contains provider-quota failures and you replace the account key, recover them into a new auditable run:

```bash
uv run --extra eval --env-file .env python tools/run_evaluation.py --recover-quota /absolute/path/to/completed-run
```

Quota recovery retains every completed answer, including incorrect answers, and every non-quota execution failure. It reruns all quota-failed executions and regenerates every judge verdict, with the same source snapshots, models, prompts, and fixtures. The original results are copied to `previous_results.json`, and each answer records its account epoch. The report explicitly labels the continuation across accounts. It does not silently replace answer-quality failures or overwrite the original run.

The checkpoint is updated after each case, judge result, and control. Ctrl+C preserves it. Resume an interrupted run with:

```bash
uv run --extra eval --env-file .env python tools/run_evaluation.py --resume /absolute/path/to/run-directory
```

Resume uses the saved repetition count, judges, source snapshots, and model configuration. It validates source, fixture, worker, harness, Python, and dependency versions before continuing. Saved execution failures and judged failures remain recorded; resume does not selectively rerun failures. Start a fresh run to evaluate a changed implementation. Pending cases remain in the planned denominator, and an incomplete report is clearly labeled; only a complete report is an official result.

The main comparison measures whole-version behavior, including native limits and context differences. It is not a causal proof that Jev compaction improved performance. The classroom notebook's cached 75% and 92% are unrelated examples and are never used as project rates.

## Local verification

```bash
uv run --extra dev --extra eval pytest
cd web
npm run test -- --run
npm run lint
npm run build
```

The evaluation tests cover routing, score validation, forced-mode independence, Auto fallback, common-answer grading, execution/service failure denominators, source isolation, settings persistence, and shared token pacing. Frontend tests cover changing the judge selection through Settings.
