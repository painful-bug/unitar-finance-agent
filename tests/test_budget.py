import json
from datetime import date
from decimal import Decimal

from finance_agent.agent import AssistantTurn
from finance_agent.budget import BudgetRule, Operand, parse_budget_rules
from finance_agent.finance import FinanceData, load_csv


LEDGER = """date,kind,category,amount,merchant
2026-07-01,income,salary,5000.00,Employer
2026-07-03,expense,groceries,120.00,Market
2026-07-10,expense,dining,40.00,Cafe
2026-07-11,expense,dining,50.00,Cafe
2026-07-12,expense,dining,60.00,Cafe
"""


class FakeParser:
    def chat(self, messages, tools=None, response_model=None):
        assert response_model is not None
        return AssistantTurn(
            content=json.dumps(
                {
                    "rules": [
                        {
                            "rule_id": "savings_target",
                            "source_text": "Save at least 20% of income.",
                            "supported": True,
                            "left": {"metric": "savings", "unit": "RM"},
                            "operator": "gte",
                            "right": {"metric": "income", "unit": "RM", "multiplier": "0.20"},
                        }
                    ]
                }
            )
        )


def test_llm_parser_returns_validated_reusable_expression() -> None:
    preview = parse_budget_rules("Save at least 20% of income.", ["groceries"], FakeParser())

    assert preview.warnings == []
    assert preview.rules[0].right.metric == "income"
    assert preview.rules[0].right.multiplier == Decimal("0.20")


def test_savings_target_resolves_against_actual_monthly_income() -> None:
    rule = FakeParser().chat([], response_model=object).content
    parsed = BudgetRule.model_validate(json.loads(rule)["rules"][0])
    data = FinanceData(load_csv(LEDGER), date(2026, 8, 15), [parsed])

    result = data.check_budget_rule("savings_target", "2026-07")

    assert result.limit == Decimal("1000.00")
    assert result.observed == Decimal("4730.00")
    assert result.status == "met"
    assert result.compliant is True


def test_filtered_count_uses_exact_boundary_and_unsupported_rule_is_safe() -> None:
    count_rule = BudgetRule(
        rule_id="three_dining_visits",
        source_text="Use restaurants at most three times per month.",
        left=Operand(metric="transaction_count", unit="count", kind="expense", category="dining"),
        operator="lte",
        right=Operand(value=Decimal("3"), unit="count"),
    )
    unsupported = BudgetRule(
        rule_id="avoid_stress",
        source_text="Avoid stressful purchases.",
        supported=False,
        unsupported_reason="stress is not represented in the ledger",
    )
    data = FinanceData(load_csv(LEDGER), date(2026, 8, 15), [count_rule, unsupported])

    boundary = data.check_budget_rule("three_dining_visits", "2026-07")
    unavailable = data.check_budget_rule("avoid_stress", "2026-07")

    assert boundary.observed == Decimal("3.00")
    assert boundary.status == "within"
    assert unavailable.status == "insufficient_evidence"
    assert unavailable.compliant is None
