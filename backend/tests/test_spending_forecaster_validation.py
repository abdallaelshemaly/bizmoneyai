from __future__ import annotations

import csv
from pathlib import Path

import joblib
import pytest
from sklearn.dummy import DummyRegressor
from sklearn.feature_extraction import DictVectorizer
from sklearn.pipeline import Pipeline

from app.ml.forecasting.train_spending_forecaster import MODEL_FAMILY, TARGET_COLUMN
from app.ml.forecasting.validate_spending_forecaster import (
    load_forecaster_artifact,
    load_forecast_rows,
    validate_artifact_feature_contract,
    validate_spending_forecaster,
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

FEATURE_COLUMNS = [
    "clean_total_expense",
    "previous_month_expense",
    "expense_2_months_ago",
    "rolling_3_month_expense_avg",
    "rolling_6_month_expense_avg",
    "expense_growth_rate",
    "expense_to_income_ratio",
    "budget_usage_ratio",
    "year",
    "month",
    "month_index",
    "total_income",
    "budget_total",
    "transaction_count",
    "expense_transaction_count",
    "income_transaction_count",
    "category_count",
    "budget_exceeded",
    "business_profile",
    "top_spend_category_1",
    "top_spend_category_2",
    "top_spend_category_3",
]


def _row(month_start: str, *, clean: float, previous: float, two_months_ago: float, target: float) -> dict[str, object]:
    year, month, _day = month_start.split("-")
    return {
        "user_id": 1,
        "business_profile": "agency",
        "month_start": month_start,
        "year": int(year),
        "month": int(month),
        "month_index": int(month),
        "total_income": 1000.0,
        "raw_total_expense": clean,
        "clean_total_expense": clean,
        "excluded_unusual_expense": 0.0,
        "budget_total": 600.0,
        "transaction_count": 10,
        "expense_transaction_count": 8,
        "income_transaction_count": 2,
        "category_count": 3,
        "max_expense_amount": 200.0,
        "previous_month_expense": previous,
        "expense_2_months_ago": two_months_ago,
        "rolling_3_month_expense_avg": clean,
        "rolling_6_month_expense_avg": clean,
        "expense_growth_rate": 0.0,
        "expense_to_income_ratio": clean / 1000.0,
        "budget_usage_ratio": clean / 600.0,
        "budget_exceeded": 0,
        "top_spend_category_1": "Marketing",
        "top_spend_category_2": "Software",
        "top_spend_category_3": "Operations",
        "next_month_total_expense": target,
    }


def _write_dataset(path: Path) -> None:
    rows = [
        _row("2026-01-01", clean=100.0, previous=90.0, two_months_ago=80.0, target=120.0),
        _row("2026-02-01", clean=120.0, previous=100.0, two_months_ago=90.0, target=130.0),
        _row("2026-03-01", clean=130.0, previous=120.0, two_months_ago=100.0, target=140.0),
    ]
    rows[1]["raw_total_expense"] = 620.0
    rows[1]["excluded_unusual_expense"] = 500.0
    rows[1]["max_expense_amount"] = 500.0

    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(rows)


def _write_artifact(path: Path, *, feature_columns: list[str] | None = None) -> None:
    features = feature_columns or FEATURE_COLUMNS
    training_features = [{column: 1.0 for column in features if column not in {"business_profile", "top_spend_category_1", "top_spend_category_2", "top_spend_category_3"}}]
    training_features[0].update(
        {
            "business_profile": "agency",
            "top_spend_category_1": "Marketing",
            "top_spend_category_2": "Software",
            "top_spend_category_3": "Operations",
        }
    )
    model = Pipeline(
        steps=[
            ("features", DictVectorizer(sparse=False)),
            ("regressor", DummyRegressor(strategy="constant", constant=125.0)),
        ]
    )
    model.fit(training_features, [125.0])
    joblib.dump(
        {
            "model": model,
            "model_name": "Test Spending Forecaster",
            "model_family": MODEL_FAMILY,
            "target_column": TARGET_COLUMN,
            "feature_columns": features,
            "metadata": {"test_rows": 2},
        },
        path,
    )


def test_validation_module_can_load_artifact(tmp_path: Path) -> None:
    artifact_path = tmp_path / "spending_forecaster.joblib"
    _write_artifact(artifact_path)

    artifact = load_forecaster_artifact(artifact_path)

    assert artifact["model_family"] == MODEL_FAMILY
    assert artifact["target_column"] == TARGET_COLUMN


def test_validation_rejects_forbidden_leakage_columns(tmp_path: Path) -> None:
    dataset_path = tmp_path / "forecast.csv"
    artifact_path = tmp_path / "spending_forecaster.joblib"
    _write_dataset(dataset_path)
    _write_artifact(artifact_path, feature_columns=[*FEATURE_COLUMNS, "raw_total_expense"])

    artifact = load_forecaster_artifact(artifact_path)
    rows = load_forecast_rows(dataset_path)

    with pytest.raises(RuntimeError, match="forbidden leakage columns"):
        validate_artifact_feature_contract(artifact, rows)


def test_validation_returns_regression_metrics(tmp_path: Path) -> None:
    dataset_path = tmp_path / "forecast.csv"
    artifact_path = tmp_path / "spending_forecaster.joblib"
    _write_dataset(dataset_path)
    _write_artifact(artifact_path)

    result = validate_spending_forecaster(artifact_path, dataset_path)

    assert result.metrics["mae"] is not None
    assert result.metrics["rmse"] is not None
    assert result.metrics["r2"] is not None
    assert result.metrics["mape"] is not None
    assert result.evaluated_rows == 2


def test_validation_predictions_are_numeric_and_non_negative(tmp_path: Path) -> None:
    dataset_path = tmp_path / "forecast.csv"
    artifact_path = tmp_path / "spending_forecaster.joblib"
    _write_dataset(dataset_path)
    _write_artifact(artifact_path)

    result = validate_spending_forecaster(artifact_path, dataset_path)
    prediction = result.examples[0]

    assert isinstance(prediction.predicted, float)
    assert prediction.predicted >= 0.0
    assert prediction.absolute_error >= 0.0
