from __future__ import annotations

import csv
import io
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

MAX_CSV_BYTES = 1_000_000
MAX_CSV_ROWS = 5_000
MONEY = Decimal("0.01")


class Transaction(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    date: date
    kind: Literal["income", "expense"]
    category: str = Field(min_length=1)
    amount: Decimal = Field(gt=0)
    merchant: str | None = None


class LookupResult(BaseModel):
    month: str
    category: str | None
    kind: str | None
    transactions: list[Transaction]
    total: Decimal
    count: int


class BudgetResult(BaseModel):
    rule_id: str
    month: str
    status: Literal["within", "over", "met", "below", "unavailable"]
    observed: Decimal | None
    limit: Decimal
    unit: Literal["RM", "percent"]


class SavingsResult(BaseModel):
    month: str
    income: Decimal
    expenses: Decimal
    savings: Decimal
    rate: Decimal | None


def _money(value: Decimal) -> Decimal:
    return value.quantize(MONEY, rounding=ROUND_HALF_UP)


def _month_bounds(month: str) -> tuple[int, int]:
    try:
        year_text, month_text = month.split("-", 1)
        year, number = int(year_text), int(month_text)
        if len(year_text) != 4 or len(month_text) != 2 or not 1 <= number <= 12:
            raise ValueError
        return year, number
    except (TypeError, ValueError):
        raise ValueError("month must use YYYY-MM") from None


def load_csv(csv_text: str) -> list[Transaction]:
    if len(csv_text.encode("utf-8")) > MAX_CSV_BYTES:
        raise ValueError("CSV exceeds 1 MB")

    reader = csv.DictReader(io.StringIO(csv_text))
    required = {"date", "kind", "category", "amount"}
    if not reader.fieldnames or not required.issubset(reader.fieldnames):
        missing = ", ".join(sorted(required - set(reader.fieldnames or [])))
        raise ValueError(f"CSV missing required columns: {missing}")

    transactions: list[Transaction] = []
    for row_number, row in enumerate(reader, start=2):
        if len(transactions) >= MAX_CSV_ROWS:
            raise ValueError(f"CSV exceeds {MAX_CSV_ROWS} rows")
        try:
            transactions.append(
                Transaction.model_validate(
                    {
                        "date": row.get("date"),
                        "kind": row.get("kind"),
                        "category": row.get("category"),
                        "amount": row.get("amount"),
                        "merchant": row.get("merchant") or None,
                    }
                )
            )
        except ValidationError as exc:
            raise ValueError(f"invalid CSV row {row_number}: {exc.errors()[0]['msg']}") from None

    if not transactions:
        raise ValueError("CSV contains no transactions")
    return transactions


class FinanceData:
    def __init__(self, transactions: list[Transaction], as_of_date: date):
        self.transactions = transactions
        self.as_of_date = as_of_date

    def lookup_transactions(
        self,
        month: str,
        category: str | None = None,
        kind: Literal["income", "expense"] | None = None,
    ) -> LookupResult:
        year, number = _month_bounds(month)
        matches = [
            item
            for item in self.transactions
            if item.date.year == year
            and item.date.month == number
            and (category is None or item.category == category)
            and (kind is None or item.kind == kind)
        ]
        return LookupResult(
            month=month,
            category=category,
            kind=kind,
            transactions=matches[:50],
            total=_money(sum((item.amount for item in matches), Decimal(0))),
            count=len(matches),
        )

    def calculate_savings_rate(self, month: str) -> SavingsResult:
        income = self.lookup_transactions(month, kind="income").total
        expenses = self.lookup_transactions(month, kind="expense").total
        savings = _money(income - expenses)
        rate = None if income == 0 else _money(savings / income * 100)
        return SavingsResult(
            month=month,
            income=income,
            expenses=expenses,
            savings=savings,
            rate=rate,
        )

    def check_budget_rule(self, rule_id: str, month: str) -> BudgetResult:
        caps = {
            "dining_monthly_cap": ("dining", Decimal("500.00")),
            "groceries_monthly_cap": ("groceries", Decimal("800.00")),
        }
        if rule_id in caps:
            category, limit = caps[rule_id]
            observed = self.lookup_transactions(month, category=category, kind="expense").total
            return BudgetResult(
                rule_id=rule_id,
                month=month,
                status="over" if observed > limit else "within",
                observed=observed,
                limit=limit,
                unit="RM",
            )
        if rule_id == "minimum_savings_rate":
            rate = self.calculate_savings_rate(month).rate
            return BudgetResult(
                rule_id=rule_id,
                month=month,
                status="unavailable" if rate is None else ("met" if rate >= 20 else "below"),
                observed=rate,
                limit=Decimal("20.00"),
                unit="percent",
            )
        raise ValueError(f"unknown budget rule: {rule_id}")
