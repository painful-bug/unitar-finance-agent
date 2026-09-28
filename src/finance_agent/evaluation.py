from __future__ import annotations

import argparse
import json
import os
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from .agent import GroqProvider, run_agent
from .context import ContextManager
from .finance import FinanceData, load_csv
from .models import Session
from .server import _demo_csv


class JudgeVerdict(BaseModel):
    correctness: int = Field(ge=0, le=2)
    grounding: int = Field(ge=0, le=2)
    relevance: int = Field(ge=0, le=2)
    avoids_guessing: int = Field(ge=0, le=2)
    acceptable: bool
    reason: str


def deterministic_check(answer: str, amounts: list[str], keywords: list[str]) -> bool:
    normalized = answer.lower().replace(",", "").replace(" ", "")
    return all(amount.replace(",", "").replace(" ", "") in normalized for amount in amounts) and all(
        keyword.lower() in answer.lower() for keyword in keywords
    )


def _judge(
    provider: GroqProvider,
    case: dict[str, Any],
    answer: str,
) -> JudgeVerdict:
    prompt = {
        "question": case["prompts"][-1],
        "answer": answer,
        "expected_amounts": case.get("expected_amounts", []),
        "expected_keywords": case.get("expected_keywords", []),
        "rubric": (
            "Score correctness, grounding in supplied finance data, relevance, and refusal to guess "
            "from 0 to 2. Mark acceptable only when correctness and grounding are both 2 and the "
            "answer does not invent unavailable facts."
        ),
    }
    turn = provider.chat(
        [
            {"role": "system", "content": "You are a strict evaluator. Return only the requested JSON schema."},
            {"role": "user", "content": json.dumps(prompt)},
        ],
        response_model=JudgeVerdict,
    )
    if not turn.content:
        raise ValueError("judge returned no content")
    return JudgeVerdict.model_validate_json(turn.content)


def run_evaluation(version: str, context_mode: str, golden_path: Path) -> dict[str, Any]:
    if not os.getenv("GROQ_API_KEY"):
        raise RuntimeError("GROQ_API_KEY is required for evaluation")
    cases = json.loads(golden_path.read_text(encoding="utf-8"))
    agent_model = os.getenv("GROQ_MODEL", "openai/gpt-oss-20b")
    judge_model = os.getenv("GROQ_JUDGE_MODEL", "openai/gpt-oss-120b")
    provider = GroqProvider(agent_model)
    judge_provider = GroqProvider(judge_model)
    context_manager = None if version == "v1" else ContextManager(
        trigger_tokens=int(os.getenv("EVAL_CONTEXT_TRIGGER_TOKENS", "1500"))
    )
    results = []

    for case in cases:
        csv_text = case.get("csv_text") or _demo_csv()
        transactions = load_csv(csv_text)
        session = Session(
            session_id=f"eval-{case['id']}",
            data=FinanceData(transactions, date(2026, 8, 15)),
            as_of_date=date(2026, 8, 15),
            context_mode=context_mode,
        )
        result = None
        for prompt in case["prompts"]:
            result = run_agent(session, prompt, provider, context_manager=context_manager)
            if result.status != "ok":
                break
        assert result is not None
        deterministic = deterministic_check(
            result.answer,
            case.get("expected_amounts", []),
            case.get("expected_keywords", []),
        )
        try:
            verdict = _judge(judge_provider, case, result.answer)
            judge_data = verdict.model_dump(mode="json")
            passed = deterministic and verdict.acceptable and result.status == "ok"
        except Exception as exc:
            judge_data = {"acceptable": False, "error": str(exc)}
            passed = False
        results.append(
            {
                "id": case["id"],
                "answer": result.answer,
                "status": result.status,
                "deterministic_pass": deterministic,
                "judge": judge_data,
                "passed": passed,
                "context": result.context.model_dump(mode="json"),
            }
        )

    passed_count = sum(item["passed"] for item in results)
    return {
        "version": version,
        "timestamp": datetime.now(UTC).isoformat(),
        "agent_model": agent_model,
        "judge_model": judge_model,
        "context_mode": "none" if version == "v1" else context_mode,
        "passed": passed_count,
        "total": len(results),
        "pass_rate": passed_count / len(results),
        "results": results,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the finance agent golden evaluation.")
    parser.add_argument("--version", choices=("v1", "final"), required=True)
    parser.add_argument("--context-mode", choices=("auto", "jev", "summary"), default="auto")
    parser.add_argument("--golden", type=Path, default=Path("evals/golden.json"))
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    try:
        report = run_evaluation(args.version, args.context_mode, args.golden)
    except RuntimeError as exc:
        parser.error(str(exc))
    output = args.output or Path(f"evals/results/{args.version}.json")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"{report['passed']}/{report['total']} passed ({report['pass_rate']:.0%}); wrote {output}")


if __name__ == "__main__":
    main()
