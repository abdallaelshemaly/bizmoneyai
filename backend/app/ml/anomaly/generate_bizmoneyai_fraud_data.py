from __future__ import annotations

import argparse
import csv
import random
from datetime import date, timedelta
from pathlib import Path


DEFAULT_OUTPUT_PATH = (
    Path(__file__).resolve().parents[3]
    / "data"
    / "processed"
    / "bizmoneyai_unusual_transactions.csv"
)
RANDOM_STATE = 42

FIELDNAMES = [
    "category_name",
    "amount",
    "type",
    "description",
    "date",
    "budget_amount",
    "budget_month",
    "budget_spent_before",
    "user_avg_amount",
    "category_avg_amount",
    "recent_transaction_count",
    "is_outlier",
    "expected_risk_level",
]

EXPENSE_CATEGORIES = [
    ("Office Supplies", 240.0, 1500.0),
    ("Software", 850.0, 4500.0),
    ("Marketing", 1200.0, 6000.0),
    ("Travel", 900.0, 4200.0),
    ("Utilities", 430.0, 2200.0),
    ("Operations", 700.0, 3800.0),
    ("Consulting", 1800.0, 9000.0),
    ("Payroll", 6200.0, 30000.0),
    ("Rent", 4200.0, 4500.0),
]

INCOME_CATEGORIES = [
    ("Sales", 9000.0),
    ("Services Revenue", 6500.0),
    ("Refunds", 700.0),
]

NORMAL_DESCRIPTIONS = [
    "Monthly vendor invoice",
    "Team subscription renewal",
    "Client meeting expense",
    "Office purchase",
    "Campaign spend",
    "Standard supplier payment",
    "Recurring business expense",
]

SUSPICIOUS_DESCRIPTIONS = [
    "Emergency vendor transfer for urgent campaign settlement",
    "Manual override wire payment for immediate supplier settlement",
    "Urgent offshore contractor transfer",
    "Rush payment outside normal approval cycle",
    "Immediate cash transfer for vendor escalation",
]


def _month_start(value: date) -> date:
    return date(value.year, value.month, 1)


def _random_date(rng: random.Random) -> date:
    return date(2026, 1, 1) + timedelta(days=rng.randint(0, 364))


def _amount(rng: random.Random, baseline: float, low: float, high: float) -> float:
    return round(max(10.0, baseline * rng.uniform(low, high)), 2)


def _normal_expense_row(rng: random.Random) -> dict[str, object]:
    category, baseline, budget = rng.choice(EXPENSE_CATEGORIES)
    tx_date = _random_date(rng)
    amount = _amount(rng, baseline, 0.25, 1.45)
    spent_before = round(budget * rng.uniform(0.05, 0.72), 2)
    return {
        "category_name": category,
        "amount": amount,
        "type": "expense",
        "description": rng.choice(NORMAL_DESCRIPTIONS),
        "date": tx_date.isoformat(),
        "budget_amount": round(budget * rng.uniform(0.85, 1.20), 2),
        "budget_month": _month_start(tx_date).isoformat(),
        "budget_spent_before": spent_before,
        "user_avg_amount": round(baseline * rng.uniform(0.85, 1.35), 2),
        "category_avg_amount": round(baseline * rng.uniform(0.80, 1.25), 2),
        "recent_transaction_count": rng.randint(2, 24),
        "is_outlier": 0,
        "expected_risk_level": "normal",
    }


def _normal_income_row(rng: random.Random) -> dict[str, object]:
    category, baseline = rng.choice(INCOME_CATEGORIES)
    tx_date = _random_date(rng)
    amount = _amount(rng, baseline, 0.45, 1.60)
    return {
        "category_name": category,
        "amount": amount,
        "type": "income",
        "description": rng.choice(["Client invoice payment", "Monthly services revenue", "Customer refund"]),
        "date": tx_date.isoformat(),
        "budget_amount": 0.0,
        "budget_month": _month_start(tx_date).isoformat(),
        "budget_spent_before": 0.0,
        "user_avg_amount": round(baseline * rng.uniform(0.85, 1.30), 2),
        "category_avg_amount": round(baseline * rng.uniform(0.80, 1.25), 2),
        "recent_transaction_count": rng.randint(1, 18),
        "is_outlier": 0,
        "expected_risk_level": "normal",
    }


def _warning_row(rng: random.Random) -> dict[str, object]:
    category, baseline, budget = rng.choice(EXPENSE_CATEGORIES)
    tx_date = _random_date(rng)
    amount = round(max(budget * rng.uniform(1.05, 2.40), baseline * rng.uniform(4.0, 8.5)), 2)
    spent_before = round(budget * rng.uniform(0.55, 1.05), 2)
    return {
        "category_name": category,
        "amount": amount,
        "type": "expense",
        "description": rng.choice(SUSPICIOUS_DESCRIPTIONS),
        "date": tx_date.isoformat(),
        "budget_amount": round(budget, 2),
        "budget_month": _month_start(tx_date).isoformat(),
        "budget_spent_before": spent_before,
        "user_avg_amount": round(baseline * rng.uniform(0.75, 1.20), 2),
        "category_avg_amount": round(baseline * rng.uniform(0.70, 1.15), 2),
        "recent_transaction_count": rng.randint(0, 4),
        "is_outlier": 1,
        "expected_risk_level": "warning",
    }


def _critical_row(rng: random.Random) -> dict[str, object]:
    category, baseline, budget = rng.choice(EXPENSE_CATEGORIES)
    tx_date = _random_date(rng)
    amount = round(max(budget * rng.uniform(4.0, 14.0), baseline * rng.uniform(14.0, 32.0)), 2)
    spent_before = round(budget * rng.uniform(0.70, 1.45), 2)
    return {
        "category_name": category,
        "amount": amount,
        "type": "expense",
        "description": rng.choice(SUSPICIOUS_DESCRIPTIONS),
        "date": tx_date.isoformat(),
        "budget_amount": round(budget, 2),
        "budget_month": _month_start(tx_date).isoformat(),
        "budget_spent_before": spent_before,
        "user_avg_amount": round(baseline * rng.uniform(0.70, 1.10), 2),
        "category_avg_amount": round(baseline * rng.uniform(0.70, 1.10), 2),
        "recent_transaction_count": rng.randint(0, 3),
        "is_outlier": 1,
        "expected_risk_level": "critical",
    }


def generate_dataset(output_path: Path, *, normal_rows: int, outlier_rows: int, random_state: int) -> None:
    rng = random.Random(random_state)
    rows: list[dict[str, object]] = []

    for _ in range(normal_rows):
        rows.append(_normal_income_row(rng) if rng.random() < 0.18 else _normal_expense_row(rng))

    warning_rows = outlier_rows // 2
    critical_rows = outlier_rows - warning_rows
    for _ in range(warning_rows):
        rows.append(_warning_row(rng))
    for _ in range(critical_rows):
        rows.append(_critical_row(rng))

    rng.shuffle(rows)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(rows)

    print(f"Generated {len(rows)} BizMoneyAI transaction rows at {output_path}")
    print(f"- normal rows: {normal_rows}")
    print(f"- outlier rows: {outlier_rows}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate BizMoneyAI-style unusual transaction training data.")
    parser.add_argument("--output-path", type=Path, default=DEFAULT_OUTPUT_PATH)
    parser.add_argument("--normal-rows", type=int, default=5000)
    parser.add_argument("--outlier-rows", type=int, default=900)
    parser.add_argument("--random-state", type=int, default=RANDOM_STATE)
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    generate_dataset(
        args.output_path,
        normal_rows=args.normal_rows,
        outlier_rows=args.outlier_rows,
        random_state=args.random_state,
    )
