from datetime import date
from decimal import Decimal

import pytest

from finance_agent.finance import FinanceData, load_csv


LEDGER = """date,kind,category,amount,merchant
2026-07-01,income,salary,5000.00,Employer
2026-07-03,expense,groceries,120.40,Market
2026-07-10,expense,dining,510.00,Cafe
"""


def test_finance_tools_return_grounded_totals_and_budget_status() -> None:
    data = FinanceData(load_csv(LEDGER), date(2026, 8, 15))

    groceries = data.lookup_transactions("2026-07", category="groceries")
    dining = data.check_budget_rule("dining_monthly_cap", "2026-07")
    savings = data.calculate_savings_rate("2026-07")

    assert groceries.total == Decimal("120.40")
    assert groceries.count == 1
    assert dining.status == "over"
    assert dining.observed == Decimal("510.00")
    assert savings.rate == Decimal("87.39")


def test_csv_validation_reports_the_bad_row() -> None:
    with pytest.raises(ValueError, match="row 2"):
        load_csv("date,kind,category,amount\n2026-07-01,other,x,-1")


def test_csv_accepts_a_40k_row_ledger() -> None:
    rows = "\n".join(
        f"2026-07-{index % 28 + 1:02d},expense,groceries,1.00,Market"
        for index in range(40_000)
    )

    assert len(load_csv(f"date,kind,category,amount,merchant\n{rows}")) == 40_000


def test_zero_income_has_no_savings_rate() -> None:
    data = FinanceData(
        load_csv("date,kind,category,amount\n2026-07-01,expense,dining,10"),
        date(2026, 8, 15),
    )

    assert data.calculate_savings_rate("2026-07").rate is None
    assert data.check_budget_rule("minimum_savings_rate", "2026-07").status == "unavailable"


def test_shared_rule_for_absent_category_is_insufficient_evidence():
    from datetime import date
    from finance_agent.budget import default_budget_rules

    ledger = FinanceData(load_csv("date,kind,category,amount\n2026-08-01,income,salary,1000"), date(2026, 8, 15), default_budget_rules())
    result = ledger.check_budget_rule("dining_monthly_cap", "2026-08")
    assert result.status == "insufficient_evidence" and result.compliant is None
    assert "dining" in result.reason
