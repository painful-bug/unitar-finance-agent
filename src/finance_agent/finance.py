from __future__ import annotations

import csv
import io
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from .budget import BudgetResult, BudgetRule, Operand, default_budget_rules

MAX_CSV_BYTES = 10_000_000
MAX_CSV_ROWS = 50_000
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
        raise ValueError("CSV exceeds 10 MB")

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
    def __init__(
        self,
        transactions: list[Transaction],
        as_of_date: date,
        budget_rules: list[BudgetRule] | None = None,
    ):
        self.transactions = transactions
        self.as_of_date = as_of_date
        self.budget_rules = list(budget_rules) if budget_rules is not None else default_budget_rules()

    def _matches(
        self,
        month: str,
        category: str | None = None,
        kind: Literal["income", "expense"] | None = None,
        merchant: str | None = None,
    ) -> list[Transaction]:
        year, number = _month_bounds(month)
        return [
            item
            for item in self.transactions
            if item.date.year == year
            and item.date.month == number
            and (category is None or item.category.casefold() == category.casefold())
            and (kind is None or item.kind == kind)
            and (
                merchant is None
                or (item.merchant is not None and item.merchant.casefold() == merchant.casefold())
            )
        ]

    def lookup_transactions(
        self,
        month: str,
        category: str | None = None,
        kind: Literal["income", "expense"] | None = None,
    ) -> LookupResult:
        matches = self._matches(month, category=category, kind=kind)
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

    def _resolve_operand(self, operand: Operand, month: str) -> tuple[Decimal | None, dict[str, object]]:
        if operand.value is not None:
            return operand.value, {"value": operand.value, "unit": operand.unit}

        metric = operand.metric
        assert metric is not None
        if metric in {"income", "expenses", "savings", "savings_rate"}:
            savings = self.calculate_savings_rate(month)
            values = {
                "income": savings.income,
                "expenses": savings.expenses,
                "savings": savings.savings,
                "savings_rate": savings.rate,
            }
            raw = values[metric]
            value = None if raw is None else _money(raw * operand.multiplier)
            return value, {
                "metric": metric,
                "raw": raw,
                "multiplier": operand.multiplier,
                "unit": operand.unit,
            }

        matches = self._matches(
            month,
            category=operand.category,
            kind=operand.kind,
            merchant=operand.merchant,
        )
        amounts = [item.amount for item in matches]
        if metric == "transaction_count":
            raw = Decimal(len(matches))
        elif metric == "transaction_sum":
            raw = sum(amounts, Decimal(0))
        elif not amounts:
            raw = None
        elif metric == "transaction_average":
            raw = sum(amounts, Decimal(0)) / len(amounts)
        elif metric == "transaction_minimum":
            raw = min(amounts)
        else:
            raw = max(amounts)
        value = None if raw is None else _money(raw * operand.multiplier)
        return value, {
            "metric": metric,
            "raw": raw,
            "multiplier": operand.multiplier,
            "kind": operand.kind,
            "category": operand.category,
            "merchant": operand.merchant,
            "matched_transactions": len(matches),
            "unit": operand.unit,
        }

    def check_budget_rule(self, rule_id: str, month: str) -> BudgetResult:
        rule = next((item for item in self.budget_rules if item.rule_id == rule_id), None)
        if rule is None:
            raise ValueError(f"unknown budget rule: {rule_id}")
        if not rule.supported:
            return BudgetResult(
                rule_id=rule.rule_id,
                source_text=rule.source_text,
                month=month,
                status="insufficient_evidence",
                compliant=None,
                observed=None,
                limit=None,
                unit=None,
                reason=rule.unsupported_reason,
            )

        assert rule.left and rule.operator and rule.right
        missing = next((operand.category for operand in (rule.left, rule.right)
                        if operand.category and not any(item.category.casefold() == operand.category.casefold() for item in self.transactions)), None)
        if missing:
            return BudgetResult(rule_id=rule.rule_id, source_text=rule.source_text, month=month,
                                status="insufficient_evidence", compliant=None, observed=None,
                                limit=None, unit=rule.left.unit, operator=rule.operator,
                                reason=f"the ledger does not contain category: {missing}")
        observed, left_evidence = self._resolve_operand(rule.left, month)
        limit, right_evidence = self._resolve_operand(rule.right, month)
        if observed is None or limit is None:
            missing_status = "unavailable" if rule.rule_id == "minimum_savings_rate" else "insufficient_evidence"
            return BudgetResult(
                rule_id=rule.rule_id,
                source_text=rule.source_text,
                month=month,
                status=missing_status,
                compliant=None,
                observed=observed,
                limit=limit,
                unit=rule.left.unit,
                operator=rule.operator,
                evidence={"left": left_evidence, "right": right_evidence},
                reason="the ledger does not contain enough data to resolve both operands",
            )

        comparisons = {
            "lt": observed < limit,
            "lte": observed <= limit,
            "eq": observed == limit,
            "gte": observed >= limit,
            "gt": observed > limit,
        }
        compliant = comparisons[rule.operator]
        is_cap = rule.operator in {"lt", "lte"} and rule.left.metric in {
            "expenses",
            "transaction_sum",
            "transaction_average",
            "transaction_maximum",
            "transaction_count",
        }
        is_minimum = rule.operator in {"gt", "gte"} and rule.left.metric in {
            "income",
            "savings",
            "savings_rate",
        }
        status = (
            ("within" if compliant else "over")
            if is_cap
            else ("met" if compliant else "below")
            if is_minimum
            else ("compliant" if compliant else "violated")
        )
        return BudgetResult(
            rule_id=rule.rule_id,
            source_text=rule.source_text,
            month=month,
            status=status,
            compliant=compliant,
            observed=observed,
            limit=limit,
            unit=rule.left.unit,
            operator=rule.operator,
            evidence={"left": left_evidence, "right": right_evidence},
        )
