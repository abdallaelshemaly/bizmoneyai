from __future__ import annotations

import csv
from pathlib import Path

import pytest

from app.ml.forecasting.train_spending_forecaster import (
    FEATURE_COLUMNS,
    FORBIDDEN_FEATURE_COLUMNS,
    load_training_records,
)


FIELDNAMES = [
    "user_id",
    "business_profile",
    "month_start",
    "year",
    "month",
    "month_index",
    "total_income",
    "raw_total_expense",
    "clean_total_expense",
    "excluded_unusual_expense",
    "budget_total",
    "transaction_count",
    "expense_transaction_count",
    "income_transaction_count",
    "category_count",
    "avg_expense_amount",
    "max_expense_amount",
    "previous_month_expense",
    "expense_2_months_ago",
    "rolling_3_month_expense_avg",
    "rolling_6_month_expense_avg",
    "expense_growth_rate",
    "expense_to_income_ratio",
    "budget_usage_ratio",
    "budget_exceeded",
    "top_spend_category_1",
    "top_spend_category_2",
    "top_spend_category_3",
    "next_month_total_expense",
]


def _base_row(month_start: str, *, clean_expense: float, previous_expense: float, two_months_ago: float) -> dict[str, object]:
    year, month, _day = month_start.split("-")
    return {
        "user_id": 1,
        "business_profile": "freelance_agency",
        "month_start": month_start,
        "year": int(year),
        "month": int(month),
        "month_index": int(month),
        "total_income": 1000.0,
        "raw_total_expense": clean_expense,
        "clean_total_expense": clean_expense,
        "excluded_unusual_expense": 0.0,
        "budget_total": 500.0,
        "transaction_count": 12,
        "expense_transaction_count": 9,
        "income_transaction_count": 3,
        "category_count": 4,
        "avg_expense_amount": clean_expense / 9,
        "max_expense_amount": 180.0,
        "previous_month_expense": previous_expense,
        "expense_2_months_ago": two_months_ago,
        "rolling_3_month_expense_avg": clean_expense,
        "rolling_6_month_expense_avg": clean_expense,
        "expense_growth_rate": 0.0,
        "expense_to_income_ratio": clean_expense / 1000.0,
        "budget_usage_ratio": clean_expense / 500.0,
        "budget_exceeded": 0,
        "top_spend_category_1": "Marketing",
        "top_spend_category_2": "Software",
        "top_spend_category_3": "Operations",
        "next_month_total_expense": clean_expense,
    }


def _write_dataset(path: Path, rows: list[dict[str, object]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(rows)


def test_model_3_feature_policy_uses_clean_spending_columns() -> None:
    assert "clean_total_expense" in FEATURE_COLUMNS
    assert "previous_month_expense" in FEATURE_COLUMNS
    assert "rolling_3_month_expense_avg" in FEATURE_COLUMNS
    assert not (set(FEATURE_COLUMNS) & FORBIDDEN_FEATURE_COLUMNS)


def test_load_training_records_excludes_raw_unusual_spend_from_features(tmp_path: Path) -> None:
    rows = [
        _base_row("2026-01-01", clean_expense=100.0, previous_expense=90.0, two_months_ago=80.0),
        _base_row("2026-02-01", clean_expense=120.0, previous_expense=100.0, two_months_ago=90.0),
        _base_row("2026-03-01", clean_expense=130.0, previous_expense=120.0, two_months_ago=100.0),
    ]
    rows[0]["next_month_total_expense"] = 120.0
    rows[1]["raw_total_expense"] = 1120.0
    rows[1]["excluded_unusual_expense"] = 1000.0
    rows[1]["max_expense_amount"] = 1000.0
    rows[1]["next_month_total_expense"] = 130.0
    rows[2]["next_month_total_expense"] = 140.0

    dataset_path = tmp_path / "forecast.csv"
    _write_dataset(dataset_path, rows)

    records = load_training_records(dataset_path)
    unusual_month = records[1]

    assert unusual_month.features["clean_total_expense"] == 120.0
    assert unusual_month.features["previous_month_expense"] == 100.0
    assert "raw_total_expense" not in unusual_month.features
    assert "excluded_unusual_expense" not in unusual_month.features
    assert "max_expense_amount" not in unusual_month.features


def test_load_training_records_rejects_raw_next_month_target_when_unusual_spend_is_excluded(tmp_path: Path) -> None:
    rows = [
        _base_row("2026-01-01", clean_expense=100.0, previous_expense=90.0, two_months_ago=80.0),
        _base_row("2026-02-01", clean_expense=120.0, previous_expense=100.0, two_months_ago=90.0),
        _base_row("2026-03-01", clean_expense=130.0, previous_expense=120.0, two_months_ago=100.0),
    ]
    rows[0]["next_month_total_expense"] = 1120.0
    rows[1]["raw_total_expense"] = 1120.0
    rows[1]["excluded_unusual_expense"] = 1000.0
    rows[1]["next_month_total_expense"] = 130.0

    dataset_path = tmp_path / "forecast.csv"
    _write_dataset(dataset_path, rows)

    with pytest.raises(RuntimeError, match="next month's clean_total_expense"):
        load_training_records(dataset_path)
