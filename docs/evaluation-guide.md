# Run the finance prompt evaluation

This follows the instructor’s `starter_g.ipynb`: two system prompts, a fixed reference, twelve golden questions, literal keyword checks, and a separate LLM judge call. It compares **direct finance prompts**, rather than historical application versions, tools, or conversation memory. The notebook is reference material, not an instruction to execute its Colab cells.

Latest verified results: [finance prompt evaluation report](evaluation-report.md).

## One-command run

From the repository, with `uv` installed and `GROQ_API_KEY` in `.env`:

```bash
uv sync --extra eval --extra dev
uv run --extra eval --env-file .env python tools/run_evaluation.py
```

The default runs three repetitions per prompt: 72 fresh answers and 42 separate judge calls, before any SDK retries. For a shorter live demonstration:

```bash
uv run --extra eval --env-file .env python tools/run_evaluation.py --repeats 1
```

`--repeats` is the only evaluation option. Evaluation requires no TypeSafe key and makes no Jev calls. It does not read application Settings. The application’s Jev conversation-context feature is separate and remains available.

## What runs

`src/finance_agent/evaluation.py` contains the fixed finance reference, `SYSTEM_PROMPT_A`, and `SYSTEM_PROMPT_B`. Both prompts use the same recorded facts and questions. A asks the assistant to answer from the reference; B adds the notebook’s rule to answer only from the reference, admit missing information, never invent an answer, and use two or three sentences. Edit these constants to evaluate other prompts, then run a fresh comparison.

`evals/golden.json` contains twelve independent cases: five keyword cases and seven judge cases. Every answer receives only its system prompt and question. Judge criteria are sent only to the judge. There are no tools, alternate ledgers, conversation preludes, workers, Git snapshots, or source-copying steps. The earlier memory case is replaced by an unsupported bank-balance question, and the separate zero-income scenario is explicitly described in the shared reference.

The answer model is `openai/gpt-oss-20b`; the judge is `openai/gpt-oss-120b`. Both use temperature 0. The model split and fixed temperature are deliberate adaptations approved by the user; the notebook otherwise uses one model for both calls. Temperature 0 reduces variation but does not promise identical outputs.

The normal judge uses the notebook’s OpenAI-compatible Groq client, Instructor JSON mode, and `max_retries=2`. Its `AnswerJudgment` contains `passed`, `score`, and `reasoning`. Scores are validated from 1 to 5. Each case uses **keyword OR judge**, and the boolean verdict directly determines passing; there is no score threshold. Matching uses case-insensitive literal substrings, following the notebook’s stated exercise behavior instead of its completed cell’s case-sensitive bug.

## Explain the live demonstration

1. Show the two prompts and their identical finance reference. Show a keyword case and a judge case in the golden dataset.
2. Start the script. The console identifies the repetition and prompt, then prints each question and actual answer.
3. A keyword case prints its literal matches without a judge call. A semantic case prints its written criteria, verdict, score, and model-generated reasoning.
4. Each completed prompt run prints its pass count and rate. The final summary prints aggregate rates and observed ranges across repetitions.
5. Open the printed `report.md` path. `results.json` contains the exact prompts, reference, dataset, model settings, answers, and structured judgments.

## Results and failures

Every execution creates a new timestamped directory under `evals/results/` containing only `results.json` and `report.md`. Reports show every repetition, aggregate passes, mean/minimum/maximum rates, the range in percentage points, keyword/judge breakdowns, and evidence for every case. All runs are retained; answers or failures are never selectively rerun to manufacture consistent rates.

The client uses ordinary SDK retries and Instructor’s schema retries. There is no custom pacing, quota recovery, account switching, or resume mechanism. If a provider call still fails, the script saves partial evidence, marks the evaluation incomplete, and exits with a nonzero status. Incomplete runs are not the completed comparison. After fixing the provider problem, run the entire comparison again. Ctrl+C during a case also preserves partial evidence. Provider quotas can make a live run take longer or stop it.

Literal matching can accept numbers within larger numbers or negated statements, and reject equivalent wording. The judge can be inconsistent or wrong. The three-run range measures observed variation, not a guarantee of future stability. Twelve synthetic cases do not establish general financial accuracy or the actual tool-using application’s performance.

The older application-version results remain locally preserved under their original run directories. They use a different evaluation target and are not merged into this prompt comparison. The notebook’s cached example rates are also unrelated.

## Verify locally

```bash
uv run --extra dev --extra eval pytest
cd web
npm run test -- --run
npm run lint
npm run build
```

Tests cover notebook routing, structured judgment bounds, direct API call settings, repetition aggregation, partial evidence on provider failure, and old settings/chat snapshots loading after removal of the evaluation selector.
