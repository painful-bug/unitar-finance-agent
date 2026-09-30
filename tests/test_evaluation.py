import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from finance_agent import evaluation as e


def dataset():
    return json.loads(Path("evals/golden.json").read_text())


def test_dataset_and_notebook_checks():
    cases = dataset()
    assert len(cases) == len({c["id"] for c in cases}) == 12
    assert sum(c["check_type"] == "keyword" for c in cases) == 5
    assert all("prelude" not in c and "csv_text" not in c for c in cases)
    assert e.check_keywords("WITHIN budget: 690.65", ["within", "690.65"])
    assert not e.check_keywords("690.64", ["690.65"])
    assert e.check_keywords("14500", ["450"])  # notebook's literal substring limitation
    for score in (0, 6):
        with pytest.raises(ValidationError):
            e.AnswerJudgment(passed=True, score=score, reasoning="Invalid range.")
    assert e.SYSTEM_PROMPT_A.endswith(e.FINANCE_REFERENCE)
    assert e.SYSTEM_PROMPT_B.endswith(e.FINANCE_REFERENCE)


def test_direct_call_and_independent_judge_contract(monkeypatch):
    calls = []
    def create(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=" answer "))])
    monkeypatch.setattr(e, "client", SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create))))
    assert e.get_answer("system", "question") == "answer"
    assert calls[0] == {"model": e.ANSWER_MODEL, "temperature": 0, "messages": [
        {"role": "system", "content": "system"}, {"role": "user", "content": "question"}]}
    verdict = e.AnswerJudgment(passed=True, score=1, reasoning="Boolean is authoritative.")
    def judge(**kwargs):
        calls.append(kwargs)
        return verdict
    monkeypatch.setattr(e, "judge_client", SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=judge))))
    assert e.judge_answer("q", "a", "c") is verdict
    assert calls[1]["model"] == e.JUDGE_MODEL and calls[1]["max_retries"] == 2
    assert calls[1]["response_model"] is e.AnswerJudgment
    assert "Criteria: c" in calls[1]["messages"][1]["content"]


def test_keyword_or_judge_routing(monkeypatch):
    calls = []
    monkeypatch.setattr(e, "get_answer", lambda prompt, question: "ok")
    def judge(*args):
        calls.append(args)
        return e.AnswerJudgment(passed=True, score=1, reasoning="Boolean determines passing.")
    monkeypatch.setattr(e, "judge_answer", judge)
    cases = [{"id": "k", "question": "keyword", "check_type": "keyword", "must_include": ["OK"]},
             {"id": "j", "question": "semantic", "check_type": "judge", "criteria": "correct"}]
    result = e.run_eval("A", "system", cases)
    assert result["pass_rate"] == 1 and len(calls) == 1
    assert calls[0] == ("semantic", "ok", "correct")


def test_repetition_summary_and_range(tmp_path):
    cases = dataset()
    runs = []
    for name in e.PROMPTS:
        for repeat in range(1, 4):
            passed = (12, 9, 6)[repeat-1] if "baseline" in name else 12
            rows = [{**c, "answer": "saved answer", "passed": i < passed, "detail": "check"}
                    for i, c in enumerate(cases)]
            runs.append({"system": name, "repeat": repeat, "state": "complete", "pass_rate": passed/12, "results": rows})
    data = {"started_at": "test", "state": "complete", "repeats": 3, "dataset": cases, "runs": runs}
    e.write_outputs(tmp_path, data)
    summary = data["summaries"]["Prompt A (baseline)"]
    assert summary["passed"] == 27 and summary["total"] == 36
    assert summary["mean"] == .75 and summary["range"] == .5
    assert len(json.loads((tmp_path/"results.json").read_text())["runs"]) == 6
    assert "50.00 pp" in (tmp_path/"report.md").read_text()


def test_cli_provider_failure_saves_partial_evidence(monkeypatch, tmp_path):
    import instructor
    import openai
    (tmp_path/"evals").mkdir()
    (tmp_path/"evals/golden.json").write_text(json.dumps(dataset()))
    monkeypatch.setattr(e, "ROOT", tmp_path)
    monkeypatch.setenv("GROQ_API_KEY", "test-key")
    monkeypatch.setattr(e, "client", None)
    monkeypatch.setattr(e, "judge_client", None)
    monkeypatch.setattr(sys, "argv", ["eval", "--repeats", "3"])
    calls = []
    def create(**kwargs):
        calls.append(kwargs)
        if len(calls) == 2:
            raise RuntimeError("Provider quota unavailable")
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="690.65"))])
    class Client:
        chat = SimpleNamespace(completions=SimpleNamespace(create=create))
        def __enter__(self): return self
        def __exit__(self, *args): pass
    monkeypatch.setattr(openai, "OpenAI", lambda **kwargs: Client())
    monkeypatch.setattr(instructor, "from_openai", lambda client, **kwargs: client)
    with pytest.raises(SystemExit) as exc:
        e.main()
    assert exc.value.code == 1 and len(calls) == 2
    output = next((tmp_path/"evals/results").iterdir())
    data = json.loads((output/"results.json").read_text())
    assert data["state"] == "incomplete" and not data["summaries"]
    rows = data["runs"][0]["results"]
    assert rows[0]["passed"] and rows[1]["passed"] is None
    assert data["runs"][0]["pass_rate"] is None
    assert "State: **incomplete**" in (output/"report.md").read_text()
