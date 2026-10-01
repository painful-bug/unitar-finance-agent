import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from finance_agent import evaluation as e
from finance_agent.agent import GroqProvider, TOOLS
from finance_agent.models import AgentResult


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
    assert e.SYSTEM_PROMPT_A.endswith(e.BUDGET_RULES)
    assert e.SYSTEM_PROMPT_B.endswith(e.BUDGET_RULES)
    assert e.BUDGET_RULES == '\n'.join(rule.source_text for rule in e.default_budget_rules()) + '\n'
    assert '690.65' not in e.SYSTEM_PROMPT_A + e.SYSTEM_PROMPT_B
    assert not any(hasattr(e, name) for name in ('LEDGER', 'ZERO_INCOME_LEDGER', 'FINANCE_REFERENCE'))
    main = e.make_session("main")
    assert str(main.data.lookup_transactions("2026-06", "dining", "expense").total) == "450.00"
    assert str(main.data.lookup_transactions("2026-06", "groceries", "expense").total) == "820.00"
    assert str(main.data.lookup_transactions("2026-07", "groceries", "expense").total) == "690.65"
    savings = main.data.calculate_savings_rate("2026-07")
    assert tuple(str(v) for v in (savings.income, savings.expenses, savings.savings, savings.rate)) == (
        "5000.00", "3150.65", "1849.35", "36.99")
    assert main.data.check_budget_rule("dining_monthly_cap", "2026-07").status == "over"
    assert main.data.check_budget_rule("groceries_monthly_cap", "2026-07").status == "within"
    zero = e.make_session("zero_income").data.calculate_savings_rate("2026-05")
    assert str(zero.expenses) == "0.00" and zero.rate is None
    assert main.data.transactions == e.make_session("zero_income").data.transactions
    assert len(main.data.transactions) == 19
    dining = main.data.lookup_transactions("2026-07", "dining", "expense")
    assert [t.merchant for t in dining.transactions] == ['Cafe', 'Bistro']
    assert e.make_session("main").messages == []


def test_real_agent_tools_prompts_fresh_sessions_and_independent_judge(monkeypatch):
    calls = []
    def create(**kwargs):
        calls.append(kwargs)
        tool = SimpleNamespace(id="savings", function=SimpleNamespace(
            name="calculate_savings_rate", arguments='{"month":"2026-07"}' if len(calls) < 3 else '{"month":"2026-05"}'))
        message = (SimpleNamespace(content=None, tool_calls=[tool]) if len(calls) % 2 else
                   SimpleNamespace(content="Savings rate is undefined." if len(calls) == 4 else "36.99%", tool_calls=[]))
        return SimpleNamespace(choices=[SimpleNamespace(message=message)])
    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    monkeypatch.setattr(e, "provider", GroqProvider(model=e.ANSWER_MODEL, client=client, temperature=0))
    result = e.get_answer(e.SYSTEM_PROMPT_A, "question", "july_savings_rate")
    assert result.status == "ok" and result.steps == 2 and result.answer == "36.99%"
    assert result.trace[0].result["rate"] == "36.99"
    assert calls[0]["tools"] == TOOLS and calls[0]["tool_choice"] == "auto"
    assert calls[0]["model"] == e.ANSWER_MODEL and calls[0]["temperature"] == 0
    assert calls[0]["messages"][0]["content"].endswith(e.SYSTEM_PROMPT_A)
    assert "Use tools for every financial value" in calls[0]["messages"][0]["content"]
    zero = e.get_answer(e.SYSTEM_PROMPT_B, "zero question", "zero_income")
    assert zero.trace[0].result["income"] == "0.00" and zero.trace[0].result["rate"] is None
    assert calls[2]["messages"][0]["content"].endswith(e.SYSTEM_PROMPT_B)
    assert calls[2]["messages"][1:] == [{"role": "user", "content": "zero question"}]
    verdict = e.AnswerJudgment(passed=True, score=1, reasoning="Boolean is authoritative.")
    def judge(**kwargs):
        calls.append(kwargs)
        return verdict
    monkeypatch.setattr(e, "judge_client", SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=judge))))
    assert e.judge_answer("q", "a", "c") is verdict
    assert calls[-1]["model"] == e.JUDGE_MODEL and calls[-1]["max_retries"] == 2
    assert calls[-1]["response_model"] is e.AnswerJudgment
    assert "Criteria: c" in calls[-1]["messages"][1]["content"]


def test_keyword_or_judge_routing(monkeypatch):
    calls = []
    monkeypatch.setattr(e, "get_answer", lambda prompt, question, case_id: AgentResult(answer="ok", status="ok", steps=1))
    def judge(*args):
        calls.append(args)
        return e.AnswerJudgment(passed=True, score=1, reasoning="Boolean determines passing.")
    monkeypatch.setattr(e, "judge_answer", judge)
    cases = [{"id": "k", "question": "keyword", "check_type": "keyword", "must_include": ["OK"]},
             {"id": "j", "question": "semantic", "check_type": "judge", "criteria": "correct"}]
    result = e.run_eval("A", "system", cases)
    assert result["pass_rate"] == 1 and len(calls) == 1
    assert calls[0] == ("semantic", "ok", "correct")


def test_cli_runs_each_prompt_once_and_writes_short_report(monkeypatch, tmp_path):
    import instructor
    import openai
    import groq
    cases = dataset()
    (tmp_path / "evals").mkdir()
    (tmp_path / "evals/golden.json").write_text(json.dumps(cases))
    monkeypatch.setattr(e, "ROOT", tmp_path)
    monkeypatch.setenv("GROQ_API_KEY", "test-key")
    monkeypatch.setattr(sys, "argv", ["eval"])
    answers, judgments = [], []
    def answer(prompt, question, case_id):
        answers.append((prompt, case_id))
        case = next(c for c in cases if c['id'] == case_id)
        return AgentResult(answer=' '.join(case.get('must_include', ['answer'])), status='ok', steps=1)
    def judge(**kwargs):
        judgments.append(kwargs)
        passed = len(judgments) > 3
        return e.AnswerJudgment(passed=passed, score=5 if passed else 2, reasoning="Mock judgment.")
    class Client:
        chat = SimpleNamespace(completions=SimpleNamespace(create=judge))
        def __enter__(self): return self
        def __exit__(self, *args): pass
    monkeypatch.setattr(e, "get_answer", answer)
    monkeypatch.setattr(openai, "OpenAI", lambda **kwargs: Client())
    monkeypatch.setattr(groq, "Groq", lambda **kwargs: Client())
    monkeypatch.setattr(instructor, "from_openai", lambda client, **kwargs: client)
    e.main()
    assert answers == [(prompt, case['id']) for prompt in e.PROMPTS.values() for case in cases]
    assert len(judgments) == 14
    output = next((tmp_path / "evals/results").iterdir())
    data = json.loads((output / "results.json").read_text())
    assert data['state'] == 'complete' and len(data['runs']) == 2 and data['passes_per_prompt'] == 1
    assert data['summaries']['Prompt A (baseline)']['passed'] == 9
    assert data['summaries']['Prompt B (grounded)']['passed'] == 12
    report = (output / "report.md").read_text()
    assert len(report.splitlines()) < 40 and 'Prompt B scored higher by 25.00 percentage points' in report
    data['runs'][1]['pass_rate'] = .75
    for row in data['runs'][1]['results'][9:]: row['passed'] = False
    e.write_outputs(output, data)
    assert 'Tie: neither prompt scored higher' in (output / 'report.md').read_text()


def test_cli_provider_failure_saves_partial_evidence(monkeypatch, tmp_path):
    import instructor
    import openai
    import groq
    (tmp_path/"evals").mkdir()
    (tmp_path/"evals/golden.json").write_text(json.dumps(dataset()))
    monkeypatch.setattr(e, "ROOT", tmp_path)
    monkeypatch.setenv("GROQ_API_KEY", "test-key")
    monkeypatch.setattr(e, "provider", None)
    monkeypatch.setattr(e, "judge_client", None)
    monkeypatch.setattr(sys, "argv", ["eval"])
    calls = []
    def create(**kwargs):
        calls.append(kwargs)
        if len(calls) == 2:
            raise RuntimeError("Provider quota unavailable")
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="690.65", tool_calls=[]))])
    class Client:
        chat = SimpleNamespace(completions=SimpleNamespace(create=create))
        def __enter__(self): return self
        def __exit__(self, *args): pass
    monkeypatch.setattr(openai, "OpenAI", lambda **kwargs: Client())
    monkeypatch.setattr(groq, "Groq", lambda **kwargs: Client())
    monkeypatch.setattr(instructor, "from_openai", lambda client, **kwargs: client)
    with pytest.raises(SystemExit) as exc:
        e.main()
    assert exc.value.code == 1 and len(calls) == 2
    output = next((tmp_path/"evals/results").iterdir())
    data = json.loads((output/"results.json").read_text())
    assert data["state"] == "incomplete" and not data["summaries"]
    rows = data["runs"][0]["results"]
    assert rows[0]["passed"] and rows[1]["passed"] is None
    assert rows[1]["agent"]["status"] == "error"
    assert data["runs"][0]["pass_rate"] is None
    assert "State: **incomplete**" in (output/"report.md").read_text()
