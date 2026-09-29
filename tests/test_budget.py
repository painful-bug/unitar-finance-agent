import json
from datetime import date
from decimal import Decimal
from types import SimpleNamespace

from finance_agent.agent import AssistantTurn, GroqProvider
from finance_agent.budget import BudgetRule, BudgetRuleSet, Operand, parse_budget_rules
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


class DiningParser:
    def __init__(self, limit="500.00"):
        self.limit = limit

    def chat(self, messages, tools=None, response_model=None):
        return AssistantTurn(
            content=json.dumps(
                {
                    "rules": [
                        {
                            "rule_id": "dining_outside_cap",
                            "source_text": "Eating outside budget per month is maximum 500 RM.",
                            "supported": True,
                            "left": {
                                "metric": "transaction_sum",
                                "unit": "RM",
                                "kind": "expense",
                                "category": "dining",
                            },
                            "operator": "lte",
                            "right": {"value": self.limit, "unit": "RM"},
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


def test_dining_alias_uses_generator_categories_and_preserves_rm_limit() -> None:
    categories = (category for category in ["dining", "groceries"])

    preview = parse_budget_rules(
        "Eating outside budget per month is maximum 500 RM.",
        categories,
        DiningParser(),
    )

    rule = preview.rules[0]
    assert rule.supported is True
    assert rule.rule_id == "dining_monthly_cap"
    assert rule.left.category == "dining"
    assert rule.right.value == Decimal("500.00")


def test_parser_rejects_a_hallucinated_numeric_limit() -> None:
    preview = parse_budget_rules(
        "Eating outside budget per month is maximum 500 RM.",
        ["dining"],
        DiningParser(limit="700.00"),
    )

    assert preview.rules[0].supported is False
    assert preview.rules[0].unsupported_reason == "compiled value 700.00 is absent from the rule text"


def test_groq_schema_omits_unsupported_decimal_lookaround_regex() -> None:
    class Completions:
        kwargs = None

        def create(self, **kwargs):
            self.kwargs = kwargs
            content = FakeParser().chat([], response_model=BudgetRuleSet).content
            message = SimpleNamespace(content=content, tool_calls=[])
            return SimpleNamespace(choices=[SimpleNamespace(message=message)])

    completions = Completions()
    client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    GroqProvider(client=client).chat(
        [{"role": "user", "content": "compile"}],
        response_model=BudgetRuleSet,
    )

    def patterns(value):
        if isinstance(value, dict):
            return [
                item
                for key, child in value.items()
                for item in ([child] if key == "pattern" else patterns(child))
            ]
        if isinstance(value, list):
            return [item for child in value for item in patterns(child)]
        return []

    schema = completions.kwargs["response_format"]["json_schema"]["schema"]
    assert completions.kwargs["temperature"] == 0
    assert all("(?" not in pattern for pattern in patterns(schema))

    def objects(value):
        if isinstance(value, dict):
            found = [value] if value.get("type") == "object" else []
            return found + [item for child in value.values() for item in objects(child)]
        if isinstance(value, list):
            return [item for child in value for item in objects(child)]
        return []

    assert all(item.get("additionalProperties") is False for item in objects(schema))
    assert all(set(item.get("required", [])) == set(item.get("properties", {})) for item in objects(schema))


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
