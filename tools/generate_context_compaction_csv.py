"""Generate the deterministic ledger used in the Jev compaction demo."""

import csv
from datetime import date
from pathlib import Path


OUTPUT = Path(__file__).parents[1] / "src/finance_agent/data/context_compaction_demo.csv"
CATEGORIES = ("groceries", "dining", "transport", "utilities", "subscriptions", "health", "education")


def main() -> None:
    with OUTPUT.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(("date", "kind", "category", "amount", "merchant"))
        for month_index in range(100):
            year, month = divmod(4 + month_index, 12)
            year += 2018
            month += 1
            for entry in range(50):
                row = month_index * 50 + entry + 1
                income = entry == 0
                writer.writerow(
                    (
                        date(year, month, entry % 28 + 1).isoformat(),
                        "income" if income else "expense",
                        "salary" if income else CATEGORIES[(row - 1) % len(CATEGORIES)],
                        f"{5000 + month_index * 10:.2f}" if income else f"{80 + (row * 13 % 50000) / 100:.2f}",
                        f"Jev compaction audit record {row:04d}; synthetic source {year}-{month:02d}",
                    )
                )
    assert sum(1 for _ in OUTPUT.open(encoding="utf-8")) == 5_001
    assert OUTPUT.stat().st_size <= 1_000_000


if __name__ == "__main__":
    main()
