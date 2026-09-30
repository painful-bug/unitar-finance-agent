"""Notebook-style golden evaluation; remote judges never perform finance arithmetic."""
from __future__ import annotations

import argparse
import asyncio
import csv
import hashlib
import importlib.metadata
import io
import json
import math
import os
import shutil
import selectors
import time
import subprocess
import sys
import tarfile
from datetime import UTC, datetime
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

ROOT = Path(__file__).resolve().parents[2]
JEV_MODEL = "jev-1.13.0"
AUTO_CONFIDENCE = 0.65
_JUDGE_PACING_PATH: Path | None = None
_JUDGE_TRANSPORT: list[dict] = []
JUDGE_INSTRUCTION = (
    "You are a strict grader for a finance assistant's answers. Judge only "
    "against the stated criteria — do not reward a confident tone, only "
    "correctness against the criteria."
)
SCORE_LEVELS = [
    "The answer fails the stated criteria fundamentally: no relevant correct response or fabricated central facts.",
    "The answer addresses the question but has major factual errors or omits most required findings.",
    "The answer satisfies some stated criteria but misses or contradicts a substantive required finding.",
    "The answer satisfies the substantive findings but has a minor omission required by the stated criteria.",
    "The answer fully satisfies every stated criterion with correct findings and no conflicting invented claims.",
]


class GoldenCase(BaseModel):
    model_config = {"extra": "forbid"}
    id: str = Field(min_length=1)
    question: str = Field(min_length=1)
    check_type: Literal["keyword", "judge"]
    must_include: list[str] = Field(default_factory=list)
    criteria: str = ""
    prelude: list[str] = Field(default_factory=list)
    csv_text: str | None = None

    @model_validator(mode="after")
    def valid_check(self):
        if self.check_type == "keyword" and (not self.must_include or any(not s.strip() for s in self.must_include)):
            raise ValueError("keyword cases require nonempty literal strings")
        if self.check_type == "judge" and not self.criteria.strip():
            raise ValueError("judge cases require stated criteria")
        return self


class AnswerJudgment(BaseModel):
    passed: bool = Field(strict=True, description="True if the answer satisfies the stated criteria, False otherwise.")
    score: int = Field(ge=1, le=5, strict=True, description="Merit score: 1 fails badly to 5 fully satisfies the criteria.")
    reasoning: str = Field(min_length=1, description="One sentence explaining the score, naming the specific problem if it failed.")


def check_keywords(answer: str, must_include: list[str]) -> bool:
    return all(text.lower() in answer.lower() for text in must_include)


def judge_answer(question: str, answer: str, criteria: str) -> AnswerJudgment:
    """The instructor's OpenAI-compatible client + Instructor JSON technique."""
    import instructor
    from openai import OpenAI

    with OpenAI(api_key=os.environ["GROQ_API_KEY"], base_url="https://api.groq.com/openai/v1",
                timeout=30, max_retries=1) as client:
        if _JUDGE_PACING_PATH is not None:
            from .evaluation_transport import paced_completion
            client.chat.completions.create = paced_completion(client, _JUDGE_PACING_PATH, _JUDGE_TRANSPORT)
        judge_client = instructor.from_openai(client, mode=instructor.Mode.JSON)
        return judge_client.chat.completions.create(
            model=os.getenv("GROQ_JUDGE_MODEL", "openai/gpt-oss-120b"),
            response_model=AnswerJudgment,
            max_retries=2,
            messages=[
                {"role": "system", "content": JUDGE_INSTRUCTION},
                {"role": "user", "content": f"Question: {question}\n\nAssistant's answer: {answer}\n\nCriteria: {criteria}"},
            ],
        )


def _distribution(values: dict, expected: set) -> None:
    if set(values) != expected or any(not math.isfinite(v) or not 0 <= v <= 1 for v in values.values()):
        raise ValueError("invalid Jev probability distribution")
    if not math.isclose(sum(values.values()), 1, abs_tol=0.01):
        raise ValueError("Jev probabilities do not sum to one")


def jev_judgment(response) -> tuple[AnswerJudgment, dict]:
    """Map native 0..4 ordinal probabilities to the notebook's integer 1..5."""
    choice, score = response.choices["verdict"], response.scores["quality"]
    _distribution(choice.probabilities, {"pass", "fail"})
    _distribution(score.probabilities, set(range(5)))
    if choice.choice not in {"pass", "fail"} or not 0 <= score.score <= 4:
        raise ValueError("invalid Jev verdict/score")
    if any(not math.isfinite(v) or not 0 <= v <= 1 for v in (choice.confidence, score.confidence)):
        raise ValueError("invalid Jev confidence")
    level = max(sorted(score.probabilities), key=score.probabilities.get)  # ties choose lower level
    judgment = AnswerJudgment(
        passed=choice.choice == "pass", score=level + 1,
        reasoning=f"Code-generated summary: Jev chose {choice.choice}; quality level {level + 1}/5; "
                  f"Choice confidence {choice.confidence:.3f}, Score confidence {score.confidence:.3f}.",
    )
    return judgment, {"raw": response.model_dump(mode="json"), "reasoning_source": "code_generated",
                      "confidence": min(choice.confidence, score.confidence), "native_expected_score": score.score}


def judge_with_jev(question: str, answer: str, criteria: str) -> tuple[AnswerJudgment, dict]:
    from typesafe_sdk import Choice, Score, TypeSafeClient
    from .jev import JevClient

    with TypeSafeClient(api_key=os.environ["TYPESAFE_API_KEY"], model=JEV_MODEL, timeout=30) as client:
        response = JevClient(client).ask(
            state={"question": question, "answer": answer, "criteria": criteria},
            questions={
                "verdict": Choice(instructions=JUDGE_INSTRUCTION, criteria={
                    "pass": "The assistant's answer satisfies all the stated criteria.",
                    "fail": "The assistant's answer violates or omits at least one stated criterion.",
                }),
                "quality": Score(instructions=JUDGE_INSTRUCTION, criteria=SCORE_LEVELS),
            },
        )
    return jev_judgment(response)


def grade(question: str, answer: str, criteria: str, backend: str) -> tuple[AnswerJudgment, dict]:
    metadata: dict[str, Any] = {"requested_judge": backend}
    if backend in {"jev", "auto"}:
        try:
            judgment, raw = judge_with_jev(question, answer, criteria)
            metadata.update(raw, effective_judge="jev")
            if backend == "jev" or raw["confidence"] >= AUTO_CONFIDENCE:
                return judgment, metadata
            metadata["fallback_reason"] = f"Jev confidence {raw['confidence']:.3f} below {AUTO_CONFIDENCE}"
        except Exception as exc:
            if backend == "jev":
                raise
            metadata["fallback_reason"] = f"Jev error: {type(exc).__name__}: {exc}"
    transport_start = len(_JUDGE_TRANSPORT)
    judgment = judge_answer(question, answer, criteria)
    metadata["transport"] = _JUDGE_TRANSPORT[transport_start:]
    metadata.update(effective_judge="llm", reasoning_source="model_generated",
                    model=os.getenv("GROQ_JUDGE_MODEL", "openai/gpt-oss-120b"))
    return judgment, metadata


def run_eval(system_name: str, cases: list[dict], answers: list[dict], backend: str,
             completed: list[dict] | None = None, checkpoint=None) -> dict:
    """Notebook routing: keyword OR judge; score never gates the boolean verdict."""
    results = completed if completed is not None else []
    for case, result in zip(cases[len(results):], answers[len(results):], strict=True):
        print(f"\nGRADING {system_name} / {backend} / {case['id']} ({case['check_type']})", flush=True)
        item = {"system": system_name, "repeat": result["repeat"], "id": case["id"],
                "question": case["question"], "answer": result["answer"], "check_type": case["check_type"],
                "status": result["status"], "passed": False}
        try:
            if result["status"] != "ok":
                item["detail"] = f"Execution failure: {result['status']}"
            elif case["check_type"] == "keyword":
                item["passed"] = check_keywords(result["answer"], case["must_include"])
                item["matches"] = {word: word.lower() in result["answer"].lower() for word in case["must_include"]}
                item["detail"] = "keyword check"
                print("  literal matches: " + json.dumps(item["matches"]), flush=True)
            else:
                print("  criteria: " + case["criteria"], flush=True)
                judgment, metadata = grade(case["question"], result["answer"], case["criteria"], backend)
                item.update(passed=judgment.passed, judgment=judgment.model_dump(), judge_metadata=metadata,
                            detail=f"judge score {judgment.score}/5 — {judgment.reasoning}")
                if "raw" in metadata:
                    print("  Jev raw decisions: " + json.dumps(metadata["raw"], ensure_ascii=False), flush=True)
                if metadata.get("fallback_reason"):
                    print("  Auto fallback: " + metadata["fallback_reason"], flush=True)
        except Exception as exc:
            item.update(detail=f"Judge service/validation error: {type(exc).__name__}: {exc}", judge_error=True)
        print(f"  {'PASS' if item['passed'] else 'FAIL'} — {item['detail']}", flush=True)
        results.append(item)
        if checkpoint:
            checkpoint()
    return {"system": system_name, "results": results, "pass_rate": sum(r["passed"] for r in results) / len(cases)}


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save_json(path: Path, value: Any) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    temporary.replace(path)


def verify_reference(ledger: str) -> dict:
    """Independent stdlib CSV + Decimal oracle, never the finance tools under test."""
    rows = list(csv.DictReader(io.StringIO(ledger)))
    def total(month, kind, category=None):
        return sum((Decimal(r["amount"]) for r in rows if r["date"].startswith(month)
                    and r["kind"] == kind and (category is None or r["category"] == category)), Decimal(0))
    groceries = total("2026-07", "expense", "groceries")
    dining = total("2026-07", "expense", "dining")
    june_dining = total("2026-06", "expense", "dining")
    income, expenses = total("2026-07", "income"), total("2026-07", "expense")
    rate = ((income - expenses) / income * 100).quantize(Decimal(".01"), rounding=ROUND_HALF_UP)
    if (groceries, dining, june_dining, rate) != tuple(map(Decimal, ["690.65", "560", "450", "36.99"])):
        raise ValueError("golden ledger no longer matches the frozen reference facts")
    return {"july_groceries": str(groceries), "july_dining": str(dining), "june_dining": str(june_dining),
            "july_income": str(income), "july_expenses": str(expenses), "july_savings_rate": str(rate),
            "dining_cap": "500", "groceries_cap": "800", "as_of_date": "2026-08-15"}


def freeze_sources(output: Path) -> dict:
    baseline = subprocess.check_output(["git", "rev-parse", "v0.1-baseline^{commit}"], cwd=ROOT, text=True).strip()
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    source = output / "sources"
    first, final = source / "baseline", source / "final"
    first.mkdir(parents=True)
    archive = subprocess.check_output(["git", "archive", baseline, "src", "pyproject.toml", "uv.lock"], cwd=ROOT)
    with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
        tar.extractall(first, filter="data")
    shutil.copytree(ROOT / "src", final / "src", ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    for name in ("pyproject.toml", "uv.lock"):
        shutil.copy2(ROOT / name, final / name)
    shutil.copy2(ROOT / "tools/evaluation_worker.py", source / "evaluation_worker.py")
    shutil.copy2(ROOT / "src/finance_agent/evaluation_transport.py", source / "evaluation_transport.py")
    shutil.copy2(Path(__file__), source / "evaluation_harness.py")
    (source / "workspace.patch").write_bytes(subprocess.check_output(["git", "diff", "HEAD"], cwd=ROOT))
    versions = {}
    for name, directory in (("baseline", first), ("final", final)):
        hashes = {str(p.relative_to(directory)): digest(p) for p in sorted(directory.rglob("*")) if p.is_file()}
        versions[name] = {"commit": baseline if name == "baseline" else head, "file_hashes": hashes,
                          "snapshot_sha256": hashlib.sha256(json.dumps(hashes, sort_keys=True).encode()).hexdigest(),
                          "native_step_limit": 6 if name == "baseline" else 15,
                          "context": "none" if name == "baseline" else "auto: 15 turns / 8000 estimated tokens"}
    return versions


async def _mcp_settings(url: str) -> dict:
    import httpx2
    from mcp import ClientSession
    from mcp.client.streamable_http import streamable_http_client

    async with httpx2.AsyncClient(timeout=3) as http:
        async with streamable_http_client(url, http_client=http) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.call_tool("get_app_settings", {})
                if result.is_error:
                    raise ValueError("MCP get_app_settings failed")
                return result.structured_content or json.loads(result.content[0].text)


def resolve_judge(override: str | None, mcp_url: str | None) -> tuple[str, str]:
    if override:
        return override, "CLI override"
    url = mcp_url or f"http://127.0.0.1:{os.getenv('MCP_PORT', '8000')}/mcp"
    try:
        settings = asyncio.run(asyncio.wait_for(_mcp_settings(url), timeout=5))
        selected = settings["evaluation_judge"]
        if selected not in {"auto", "jev", "llm"}:
            raise ValueError("invalid judge setting from MCP")
        return selected, f"running MCP settings at {url}"
    except Exception as exc:
        if mcp_url:
            raise RuntimeError(f"Explicit MCP URL unavailable: {exc}") from exc
        from .threads import ChatStore
        return ChatStore().load_settings().evaluation_judge, f"persisted host settings (MCP unavailable: {type(exc).__name__})"


def get_answer(case: dict, version: str, repeat: int, output: Path) -> dict:
    """Run the actual frozen agent in a fresh process, with its own imports."""
    job = {"case": case, "repeat": repeat, "version": version,
           "csv_text": case.get("csv_text") or (output / "ledger.csv").read_text(),
           "agent_model": os.getenv("GROQ_MODEL", "openai/gpt-oss-20b")}
    request, response = output / "worker-input.json", output / "worker-output.json"
    save_json(request, job)
    response.unlink(missing_ok=True)
    env = {**os.environ, "PYTHONPATH": str(output / "sources" / version / "src")}
    command = [sys.executable, "-u", str(output / "sources/evaluation_worker.py"), str(request), str(response)]
    try:
        process = subprocess.Popen(command, cwd=output / "sources" / version, env=env,
                                   stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
        try:
            started = time.monotonic()
            with selectors.DefaultSelector() as selector:
                selector.register(process.stdout, selectors.EVENT_READ)
                while selector.get_map():
                    if time.monotonic() - started > 1800:
                        raise subprocess.TimeoutExpired(command, 1800)
                    for key, _ in selector.select(timeout=1):
                        line = key.fileobj.readline()
                        if line:
                            print(line, end="", flush=True)
                        else:
                            selector.unregister(key.fileobj)
            if process.wait() != 0:
                raise subprocess.CalledProcessError(process.returncode, command)
        finally:
            if process.poll() is None:
                process.kill()
                process.wait()
            process.stdout.close()
        return json.loads(response.read_text())
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError, json.JSONDecodeError) as exc:
        return {"id": case["id"], "version": version, "repeat": repeat, "answer": "",
                "status": "worker_error", "error": str(exc), "turns": []}


def write_report(output: Path, data: dict) -> None:
    cases, repeats = data["cases"], data["config"]["repeats"]
    total = len(cases) * repeats
    lines = ["# Finance agent golden evaluation", "", f"Run: `{data['started_at']}`. State: **{data['state']}**.", "",
             "Real remote agent calls; frozen synthetic CSV; 12 cases (5 keyword, 7 judge). "
             "The same saved answers are used by each independent judge. No cached notebook grades are used.", "",
             "| Judge | First version | Final version | Change |", "|---|---:|---:|---:|"]
    for backend in data["config"]["judges"]:
        counts = [sum(r["passed"] for r in data["grades"].get(f"{version}/{backend}", [])) for version in ("baseline", "final")]
        lines.append(f"| {backend.upper()} | {counts[0]}/{total} ({counts[0]/total:.2%}) | {counts[1]}/{total} ({counts[1]/total:.2%}) | {(counts[1]-counts[0])/total*100:+.2f} pp |")
    execution_errors = sum(a["status"] != "ok" for a in data["answers"])
    judge_errors = sum(r.get("judge_error", False) for rows in data["grades"].values() for r in rows)
    lines += ["", f"Execution failures: **{execution_errors}**; judge service/validation failures: **{judge_errors}**."]
    if execution_errors or judge_errors:
        lines += ["", "**Service or execution failures limit interpretation of these rates. They remain failures in the denominator; do not treat the aggregate as a clean answer-quality comparison.**"]
    if data.get("recovery"):
        recovery = data["recovery"]
        lines += ["", "## Quota recovery provenance", "",
                  f"Continued from `{recovery['previous_run']}` after the user supplied a replacement Groq key. "
                  f"Retained {recovery['retained_answers']} completed answers, including answer-quality failures; "
                  f"reran all {recovery['quota_executions_to_retry']} quota-failed executions. "
                  "Every judge verdict was regenerated on the full completed corpus, using the same frozen criteria. "
                  "The original results are preserved in `previous_results.json`; `results.json` lists every retried case. "
                  "Agent source snapshots, model choices, fixtures, and prompts were unchanged. This is a quota-recovery continuation. "
                  "Account epochs identify credential stages, not verified distinct accounts."]
    lines += ["", "A pending or failed execution remains in the planned denominator; incomplete runs are not official results. "
              "The notebook's boolean `passed` determines the rate; the 1–5 score is descriptive, with no score threshold.", "",
              "## Breakdown", "", "| Judge | Version | Repeat | Keyword | Judge | Overall | Execution errors | Judge errors |",
              "|---|---|---:|---:|---:|---:|---:|---:|"]
    for backend in data["config"]["judges"]:
        for version in ("baseline", "final"):
            rows = data["grades"].get(f"{version}/{backend}", [])
            for repeat in range(1, repeats + 1):
                group = [r for r in rows if r["repeat"] == repeat]
                kw = sum(r["passed"] for r in group if r["check_type"] == "keyword")
                judge = sum(r["passed"] for r in group if r["check_type"] == "judge")
                lines.append(f"| {backend} | {version} | {repeat} | {kw}/5 | {judge}/7 | {kw+judge}/12 | {sum(r['status'] != 'ok' for r in group)} | {sum(r.get('judge_error', False) for r in group)} |")
    lines += ["", "## Case results and changes", "", "Counts show passes across repetitions; all failure evidence follows below.", "",
              "| Case | Check | " + " | ".join(f"{j} first → final" for j in data["config"]["judges"]) + " |",
              "|---|---|" + "---|" * len(data["config"]["judges"])]
    for case in cases:
        cells = []
        for backend in data["config"]["judges"]:
            counts = [sum(r["passed"] for r in data["grades"].get(f"{v}/{backend}", []) if r["id"] == case["id"]) for v in ("baseline", "final")]
            cells.append(f"{counts[0]}/{repeats} → {counts[1]}/{repeats}")
        lines.append(f"| {case['id']} | {case['check_type']} | " + " | ".join(cells) + " |")
    if set(data["config"]["judges"]) == {"llm", "jev"}:
        lines += ["", "## Judge disagreements", ""]
        disagreements = 0
        for version in ("baseline", "final"):
            llm = data["grades"].get(f"{version}/llm", [])
            jev = data["grades"].get(f"{version}/jev", [])
            for a, b in zip(llm, jev):
                if a["passed"] != b["passed"]:
                    disagreements += 1
                    lines.append(f"- {version}, repeat {a['repeat']}, {a['id']}: LLM {'PASS' if a['passed'] else 'FAIL'}, Jev {'PASS' if b['passed'] else 'FAIL'}. LLM: {a['detail']} Jev: {b['detail']}")
        if not disagreements:
            lines.append("No boolean verdict disagreements on graded answers.")
    lines += ["", "## Failure evidence", ""]
    failed = False
    for key, rows in data["grades"].items():
        for row in rows:
            if not row["passed"]:
                failed = True
                lines += [f"### {key}, repeat {row['repeat']}, {row['id']}", "", row["detail"], "",
                          "```text", row["answer"], "```", ""]
    if not failed:
        lines.append("No failures among graded answers.")
    lines += ["", "## Context diagnostics", ""]
    for answer in data["answers"]:
        if answer["id"] == "sixteen_turn_context":
            reports = [t.get("context", {}) for t in answer["turns"]]
            active = [r for r in reports if r.get("strategy", "none") != "none"]
            lines.append(f"- {answer['version']}, repeat {answer['repeat']}: {len(answer['turns'])}/16 turns completed; {len(active)} final-turn context reports used compaction. Strategies: {[r['strategy'] for r in active]}. "
                         f"Fallback reasons: {[r.get('fallback_reason') for r in active if r.get('fallback_reason')]}. Full per-step events are in results.json.")
    lines += ["", "## Provenance and controls", "", f"Judge selection: {data['config']['selection_source']}.", "",
              f"Agent model: `{data['config']['agent_model']}`. LLM judge: `{data['config']['llm_model']}`. Jev judge: `{JEV_MODEL}`.", "",
              "Both versions use shared header-driven Groq token pacing and bounded transport retries; requests, usage, pauses, and retries are recorded. "
              "See [Groq rate-limit headers](https://console.groq.com/docs/rate-limits) for the transport protocol. "
              "Both source snapshots use the same installed dependency runtime recorded below; historical dependency versions are not recreated. "
              "The baseline retains its native six-step limit and no context manager; final retains fifteen steps and Auto context. "
              "This measures whole-version behavior, not an isolated causal test of compaction or a prompt-only A/B test.", ""]
    for version, provenance in data["versions"].items():
        lines.append(f"- {version}: commit `{provenance['commit']}`, source hash `{provenance['snapshot_sha256']}`. Final includes the uncommitted workspace files at freeze time.")
    lines += ["", "Installed runtime: `" + json.dumps(data["dependencies"], sort_keys=True) + "`.", "",
              f"Golden dataset SHA-256: `{data['config']['golden_sha256']}`. Ledger SHA-256: `{data['config']['ledger_sha256']}`.", "",
              "Independent Decimal reference: `" + json.dumps(data["reference"], sort_keys=True) + "`.", "",
              "Judge controls (separate from the golden denominator):", ""]
    for backend, controls in data["controls"].items():
        for control in controls:
            lines.append(f"- {backend}/{control['name']}: expected {control['expected']}; observed {control.get('judgment', {}).get('passed')}; {'OK' if control['ok'] else 'FAILED'}. {control.get('error', '')}")
    lines += ["", "## Notebook fidelity and limitations", "",
              "| Notebook technique | Implementation |", "|---|---|",
              "| 12 golden cases: 5 keyword, 7 judge | Same partition, adapted to finance |",
              "| Case-insensitive substring match | Literal `lower()` matching; no numeric or synonym normalization |",
              "| AnswerJudgment: passed, score, reasoning | Same three fields; score validated 1–5 |",
              "| OpenAI + Instructor JSON, max_retries=2 | Same normal-LLM technique and question/answer/criteria prompt |",
              "| Keyword OR judge routing | Same single assigned check per case |",
              "| Boolean mean pass rate | Same; execution and judge service errors count as failures |",
              "| Jev adaptation | Choice verdict + five descriptive Score levels; modal level + 1, lower-level tie break |", "",
              "The notebook's completed keyword cell is case-sensitive despite its exercise instructions; this implementation follows the requested case-insensitive behavior. "
              "The completed notebook leaves scores unbounded; this implementation enforces its stated 1–5 range. "
              "Jev summaries are generated by code and are not model explanations; native weighted scores, confidence, probabilities, model, and usage are preserved. "
              "Forced Jev never falls back or changes its verdict because of low confidence. Auto falls back below 0.65 on either decision; a confident fail remains a fail. "
              "The threshold is a provisional policy, not a calibrated probability of correctness.", "",
              "Literal checks can accept a number inside a larger number or negated statement and can reject equivalent formatting such as a comma-separated value. "
              "Judges may be wrong or inconsistent; controls and disagreement evidence aid inspection, and no manual verdict overrides are applied. "
              "A dozen synthetic cases and three repetitions do not establish general performance. "
              "Provider model behavior may change; source/fixture hashes and runtime versions reproduce the setup, not identical stochastic outputs. "
              "The notebook's cached 75% and 92% are unrelated classroom results.", "",
              "Jev method references: [Choice](https://docs.typesafe.ai/primitives/choice), [Score](https://docs.typesafe.ai/primitives/score), "
              "[confidence](https://docs.typesafe.ai/confidence).", "",
              "See `results.json` for every answer, trace, verdict, and raw Jev response; `transcript.txt` contains the verbose execution log."]
    (output / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def recover_quota(previous: Path, output: Path) -> dict:
    """Explicit recovery retains answer-quality failures; only quota errors are replaced."""
    old = json.loads((previous / "results.json").read_text())
    if old["state"] != "complete":
        raise ValueError("Use --resume for an incomplete run")
    for version, provenance in old["versions"].items():
        for filename, expected in provenance["file_hashes"].items():
            if digest(previous / "sources" / version / filename) != expected:
                raise ValueError("Previous source snapshot changed")
    for filename, key in (("golden.json", "golden_sha256"), ("ledger.csv", "ledger_sha256")):
        if digest(previous / filename) != old["config"][key]:
            raise ValueError("Previous fixture changed")
    for package, expected in old["dependencies"].items():
        actual = sys.version.split()[0] if package == "python" else importlib.metadata.version(package)
        if actual != expected:
            raise ValueError("Runtime changed; start a fresh run")
    failed = [a for a in old["answers"] if a["status"] != "ok" and "rate_limit_exceeded" in a["answer"]]
    if not failed:
        raise ValueError("No quota-failed executions to recover")
    output.mkdir(parents=True, exist_ok=False)
    shutil.copytree(previous / "sources", output / "sources")
    for filename in ("golden.json", "ledger.csv"):
        shutil.copy2(previous / filename, output / filename)
    shutil.copy2(previous / "results.json", output / "previous_results.json")
    source = output / "sources"
    (source / "evaluation_worker.py").rename(source / "evaluation_worker.previous.py")
    shutil.copy2(ROOT / "tools/evaluation_worker.py", source / "evaluation_worker.py")
    shutil.copy2(ROOT / "src/finance_agent/evaluation_transport.py", source / "evaluation_transport.py")
    shutil.copy2(Path(__file__), source / "evaluation_harness.py")
    data = dict(old)
    quota_ids = {(a["repeat"], a["version"], a["id"]) for a in failed}
    depth = old.get("recovery", {}).get("depth", 1 if old.get("recovery") else 0) + 1
    data.update(started_at=datetime.now(UTC).isoformat(), state="incomplete", grades={}, controls={}, summaries={},
                answers=[a for a in old["answers"] if (a["repeat"], a["version"], a["id"]) not in quota_ids],
                recovery={"previous_run": str(previous), "previous_results_sha256": digest(previous / "results.json"),
                          "depth": depth, "replacement_account_epoch": f"replacement_{depth}",
                          "retained_answers": len(old["answers"])-len(failed), "quota_executions_to_retry": len(failed),
                          "retried_cases": [{"repeat": a["repeat"], "version": a["version"], "id": a["id"]} for a in failed],
                          "account_change": "User supplied a replacement Groq key; a new key does not establish a different account or refreshed quota.",
                          "policy": "Keep all non-quota answers, including wrong answers; retry every quota execution; regrade the entire corpus."})
    for answer in data["answers"]:
        answer.setdefault("account_epoch", "initial")
    data.pop("finished_at", None)
    data["config"] = {**old["config"], "harness_sha256": digest(Path(__file__)),
                       "worker_sha256": digest(source / "evaluation_worker.py"),
                       "transport_sha256": digest(source / "evaluation_transport.py")}
    return data


class Tee:
    def __init__(self, terminal, logfile):
        self.terminal, self.logfile = terminal, logfile
    def write(self, value):
        self.terminal.write(value)
        self.logfile.write(value)
    def flush(self):
        self.terminal.flush()
        self.logfile.flush()
    def fileno(self):
        return self.terminal.fileno()


def main() -> None:
    global _JUDGE_PACING_PATH
    parser = argparse.ArgumentParser(description="Live notebook-style finance evaluation: real baseline vs frozen final.")
    parser.add_argument("--judge", choices=("auto", "llm", "jev", "both"), help="Overrides shared Settings. Both grades the same answers independently.")
    parser.add_argument("--repeats", type=int, default=1, help="Paired repetitions: 1 for demo; 3 for official report.")
    parser.add_argument("--output", type=Path, help="New run directory; never overwrites an existing run.")
    parser.add_argument("--recover-quota", type=Path, help="New continuation run: retain completed answers, retry only quota-failed executions, regrade everything.")
    parser.add_argument("--resume", type=Path, help="Resume an interrupted run from its saved answers/checkpoint.")
    parser.add_argument("--mcp-url", help="Read shared judge settings from this MCP backend; fail if explicitly unavailable.")
    args = parser.parse_args()
    if not 1 <= args.repeats <= 20:
        parser.error("--repeats must be between 1 and 20")
    if args.resume and args.recover_quota:
        parser.error("--resume and --recover-quota are mutually exclusive")
    if args.resume and args.output:
        parser.error("--resume and --output are mutually exclusive")
    if not os.getenv("GROQ_API_KEY"):
        parser.error("GROQ_API_KEY is required; use uv run --extra eval --env-file .env python tools/run_evaluation.py")
    if args.resume:
        output = args.resume.resolve()
        data = json.loads((output / "results.json").read_text())
        if data["config"]["harness_sha256"] != digest(Path(__file__)):
            parser.error("Harness changed; start a new run to preserve provenance")
        if data["config"]["transport_sha256"] != digest(ROOT / "src/finance_agent/evaluation_transport.py"):
            parser.error("Judge transport changed; start a new run to preserve provenance")
        if args.judge and args.judge != data["config"]["requested_judge"]:
            parser.error("--judge conflicts with saved run")
        for package, expected in data["dependencies"].items():
            actual = sys.version.split()[0] if package == "python" else importlib.metadata.version(package)
            if actual != expected:
                parser.error("Runtime dependencies changed; start a new run")
        for version, provenance in data["versions"].items():
            for filename, expected in provenance["file_hashes"].items():
                if digest(output / "sources" / version / filename) != expected:
                    parser.error("Saved source snapshot changed; start a new run")
        for filename, key in (("golden.json", "golden_sha256"), ("ledger.csv", "ledger_sha256"), ("sources/evaluation_worker.py", "worker_sha256"), ("sources/evaluation_transport.py", "transport_sha256")):
            if digest(output / filename) != data["config"][key]:
                parser.error("Saved fixture/worker changed; start a new run")
    elif args.recover_quota:
        output = (args.output or ROOT / "evals/results" / datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")).resolve()
        data = recover_quota(args.recover_quota.resolve(), output)
        if args.judge and args.judge != data["config"]["requested_judge"]:
            parser.error("--judge conflicts with recovered run")
    else:
        selected, source = resolve_judge(args.judge, args.mcp_url)
        cases = [GoldenCase.model_validate(c).model_dump(exclude_none=True) for c in json.loads((ROOT / "evals/golden.json").read_text())]
        if len(cases) != 12 or sum(c["check_type"] == "keyword" for c in cases) != 5 or len({c['id'] for c in cases}) != 12:
            parser.error("Expected the frozen 12-case dataset: 5 keyword, 7 judge, unique IDs")
        ledger = (ROOT / "evals/ledger.csv").read_text()
        reference = verify_reference(ledger)
        output = (args.output or ROOT / "evals/results" / datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")).resolve()
        output.mkdir(parents=True, exist_ok=False)
        shutil.copy2(ROOT / "evals/golden.json", output / "golden.json")
        shutil.copy2(ROOT / "evals/ledger.csv", output / "ledger.csv")
        versions = freeze_sources(output)
        dependencies = {name: importlib.metadata.version(name) for name in ("groq", "typesafe-sdk", "pydantic", "openai", "instructor")}
        dependencies["python"] = sys.version.split()[0]
        config = {"requested_judge": selected, "judges": ["llm", "jev"] if selected == "both" else [selected],
                  "selection_source": source, "repeats": args.repeats,
                  "agent_model": os.getenv("GROQ_MODEL", "openai/gpt-oss-20b"),
                  "llm_model": os.getenv("GROQ_JUDGE_MODEL", "openai/gpt-oss-120b"),
                  "summary_model": os.getenv("GROQ_SUMMARY_MODEL"), "context_jev_model": os.getenv("TYPESAFE_MODEL", "jev-latest"),
                  "golden_sha256": digest(output / "golden.json"), "ledger_sha256": digest(output / "ledger.csv"),
                  "harness_sha256": digest(Path(__file__)), "worker_sha256": digest(output / "sources/evaluation_worker.py"),
                  "transport_sha256": digest(output / "sources/evaluation_transport.py"),
                  "auto_confidence_threshold": AUTO_CONFIDENCE}
        data = {"started_at": datetime.now(UTC).isoformat(), "state": "incomplete", "config": config,
                "versions": versions, "dependencies": dependencies, "reference": reference,
                "cases": cases, "answers": [], "grades": {}, "controls": {}}
    # Resume model configuration is immutable; keys remain only in the environment.
    os.environ["GROQ_MODEL"] = data["config"]["agent_model"]
    os.environ["GROQ_JUDGE_MODEL"] = data["config"]["llm_model"]
    os.environ["TYPESAFE_MODEL"] = data["config"]["context_jev_model"]
    if data["config"]["summary_model"]:
        os.environ["GROQ_SUMMARY_MODEL"] = data["config"]["summary_model"]
    else:
        os.environ.pop("GROQ_SUMMARY_MODEL", None)
    _JUDGE_PACING_PATH = output / "groq-pacing.json"
    _JUDGE_TRANSPORT.clear()
    def checkpoint():
        save_json(output / "results.json", data)
        write_report(output, data)
    checkpoint()
    original_stdout = sys.stdout
    with (output / "transcript.txt").open("a", encoding="utf-8", buffering=1) as log:
        sys.stdout = Tee(original_stdout, log)
        try:
            print(f"FINANCE GOLDEN EVALUATION\nRun directory: {output}\nJudge: {data['config']['requested_judge']} ({data['config']['selection_source']})\n"
                  f"Repetitions: {data['config']['repeats']}; cases per version: {len(data['cases'])}\n"
                  f"Agent: {data['config']['agent_model']}; LLM judge: {data['config']['llm_model']}; Jev judge: {JEV_MODEL}\n"
                  f"Reference facts: {json.dumps(data['reference'])}\nKeyword cases never call a judge. Judge verdicts directly determine pass/fail.\n", flush=True)
            if data.get("recovery"):
                print("QUOTA RECOVERY: " + json.dumps(data["recovery"], ensure_ascii=False), flush=True)
            control_case = next(c for c in data["cases"] if c["id"] == "multi_tool_budget_and_savings")
            for backend in data["config"]["judges"]:
                controls = data["controls"].setdefault(backend, [])
                for name, answer, expected in [("correct", "July dining was RM 560, over the RM 500 budget; July savings rate was 36.99%.", True),
                                                ("incorrect", "July dining was within budget at RM 3 and the savings rate was 99%.", False)]:
                    if any(c["name"] == name and c["ok"] for c in controls):
                        continue
                    print(f"JUDGE CONTROL / {backend} / {name}", flush=True)
                    try:
                        judgment, metadata = grade(control_case["question"], answer, control_case["criteria"], backend)
                        control = {"name": name, "answer": answer, "expected": expected, "ok": judgment.passed == expected,
                                   "judgment": judgment.model_dump(), "metadata": metadata}
                        print(f"  expected={expected}; observed={judgment.passed}; score={judgment.score}/5; {judgment.reasoning}", flush=True)
                    except Exception as exc:
                        control = {"name": name, "expected": expected, "ok": False, "error": str(exc)}
                    controls[:] = [c for c in controls if c["name"] != name]
                    controls.append(control)
                    checkpoint()
                    if not control["ok"]:
                        raise RuntimeError(f"{backend} judge control failed; inspect results.json before running benchmark: {control.get('error', control.get('judgment'))}")
            for repeat in range(1, data["config"]["repeats"] + 1):
                for case in data["cases"]:
                    for version in ("baseline", "final"):
                        if any(a["id"] == case["id"] and a["version"] == version and a["repeat"] == repeat for a in data["answers"]):
                            continue
                        print(f"\n{'='*72}\nANSWER / repeat {repeat} / {version} / {case['id']}\nQuestion: {case['question']}", flush=True)
                        result = get_answer(case, version, repeat, output)
                        result["account_epoch"] = data.get("recovery", {}).get("replacement_account_epoch", "initial")
                        data["answers"].append(result)
                        checkpoint()
                        print(f"Answer saved ({result['status']}); {len(data['answers'])}/{len(data['cases'])*data['config']['repeats']*2} executions complete.", flush=True)
            order = {case["id"]: index for index, case in enumerate(data["cases"])}
            data["answers"].sort(key=lambda answer: (answer["repeat"], order[answer["id"]], answer["version"]))
            for backend in data["config"]["judges"]:
                for version in ("baseline", "final"):
                    rows = data["grades"].setdefault(f"{version}/{backend}", [])
                    answers = [a for a in data["answers"] if a["version"] == version]
                    cases = data["cases"] * data["config"]["repeats"]
                    summary = run_eval(version, cases, answers, backend, rows, checkpoint)
                    data.setdefault("summaries", {})[f"{version}/{backend}"] = {"passed": sum(r["passed"] for r in rows), "total": len(cases), "pass_rate": summary["pass_rate"]}
                    print(f"\n{version.upper()} / {backend.upper()}: {sum(r['passed'] for r in rows)}/{len(cases)} passed ({summary['pass_rate']:.2%})", flush=True)
            data["state"] = "complete"
            data["finished_at"] = datetime.now(UTC).isoformat()
            checkpoint()
            print(f"\nCOMPLETE. Read {output / 'report.md'}\nFull evidence: {output / 'results.json'}", flush=True)
        except KeyboardInterrupt:
            print("\nInterrupted. Checkpoint saved. Resume with --resume " + str(output), flush=True)
            checkpoint()
            raise SystemExit(130)
        finally:
            sys.stdout = original_stdout


if __name__ == "__main__":
    main()
