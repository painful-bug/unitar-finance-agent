"""Generate a deterministic 40,000-row finance ledger for upload testing."""

import csv
from datetime import date
from pathlib import Path


OUTPUT = Path(__file__).parents[1] / "src/finance_agent/data/large_transaction_test.csv"
CATEGORIES = ("groceries", "dining", "rent", "transport", "utilities", "health")
MERCHANTS = ("Market", "Cafe", "Landlord", "Transit", "Utility Co", "Clinic")


def main() -> None:
    with OUTPUT.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(("date", "kind", "category", "amount", "merchant"))
        for index in range(40_000):
            month_index, entry = divmod(index, 1_000)
            year, month = divmod(month_index, 12)
            year += 2023
            month += 1
            income = entry == 0
            category_index = index % len(CATEGORIES)
            writer.writerow((
                date(year, month, entry % 28 + 1).isoformat(),
                "income" if income else "expense",
                "salary" if income else CATEGORIES[category_index],
                f"{5_000 + month_index * 25:.2f}" if income else f"{10 + (index * 17 % 50_000) / 100:.2f}",
                "Employer" if income else MERCHANTS[category_index],
            ))
    assert sum(1 for _ in OUTPUT.open(encoding="utf-8")) == 40_001


if __name__ == "__main__":
    main()
