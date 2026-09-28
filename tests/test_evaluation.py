import json
from pathlib import Path

from finance_agent.evaluation import deterministic_check


def test_golden_set_has_ten_cases_and_deterministic_checks_are_literal() -> None:
    cases = json.loads(Path("evals/golden.json").read_text())

    assert len(cases) == 10
    assert len(next(case for case in cases if case["id"] == "twelve_turn_context")["prompts"]) == 12
    assert deterministic_check("You spent RM 690.65 and are within budget.", ["690.65"], ["within"])
    assert not deterministic_check("You spent RM 690.64 and are within budget.", ["690.65"], ["within"])
