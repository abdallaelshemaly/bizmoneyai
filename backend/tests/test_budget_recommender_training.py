from __future__ import annotations

import csv
from pathlib import Path

import joblib

from app.ml.budgeting.train_budget_recommender import (
    ALGORITHM,
    DEFAULT_DATASET_PATH,
    FEATURE_COLUMNS,
    MODEL_FAMILY,
    TARGET_COLUMN,
    prepare_training_data,
    train,
)


FIELDNAMES = [
    "user_id",
    "business_profile",
    "company_size",
    "month",
    "category_name",
    "category_type",
    "clean_monthly_spend",
    "current_budget",
    "previous_month_spend",
    "prev_2_month_spend",
    "prev_3_month_spend",
    "avg_3_month_spend",
    "avg_6_month_spend",
    "growth_rate_3m",
    "budget_usage_ratio",
    "overspend_amount",
    "months_over_budget_3",
    "months_over_budget_6",
    "category_share_of_total",
    "total_clean_expense",
    "recommended_budget",
    "confidence_label",
]


def _row(
    index: int,
    *,
    category_name: str = "Marketing",
    category_type: str = "expense",
    business_profile: str = "lean_startup",
    company_size: str = "micro",
) -> dict[str, object]:
    clean_spend = 500.0 + (index * 65.0)
    current_budget = 540.0 + (index * 60.0)
    previous = clean_spend - 35.0
    prev_2 = clean_spend - 55.0
    prev_3 = clean_spend - 80.0
    recommended = clean_spend * 1.18 + 40.0
    return {
        "user_id": f"user_{index}",
        "business_profile": business_profile,
        "company_size": company_size,
        "month": f"2024-{(index % 12) + 1:02d}",
        "category_name": category_name,
        "category_type": category_type,
        "clean_monthly_spend": round(clean_spend, 2),
        "current_budget": round(current_budget, 2),
        "previous_month_spend": round(previous, 2),
        "prev_2_month_spend": round(prev_2, 2),
        "prev_3_month_spend": round(prev_3, 2),
        "avg_3_month_spend": round((clean_spend + previous + prev_2) / 3.0, 2),
        "avg_6_month_spend": round((clean_spend + previous + prev_2 + prev_3) / 4.0, 2),
        "growth_rate_3m": round((clean_spend - prev_3) / prev_3, 4),
        "budget_usage_ratio": round(clean_spend / current_budget, 4),
        "overspend_amount": round(max(clean_spend - current_budget, 0.0), 2),
        "months_over_budget_3": index % 3,
        "months_over_budget_6": index % 5,
        "category_share_of_total": round(0.08 + (index * 0.01), 4),
        "total_clean_expense": round(clean_spend * 3.4, 2),
        "recommended_budget": round(recommended, 2),
        "confidence_label": "medium",
    }


def _write_dataset(path: Path, rows: list[dict[str, object]], *, extra_fieldnames: list[str] | None = None) -> None:
    fieldnames = list(FIELDNAMES)
    for fieldname in extra_fieldnames or []:
        if fieldname not in fieldnames:
            fieldnames.append(fieldname)
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _sample_rows() -> list[dict[str, object]]:
    rows = [
        _row(1, category_name="Marketing", business_profile="lean_startup", company_size="micro"),
        _row(2, category_name="Software", business_profile="lean_startup", company_size="micro"),
        _row(3, category_name="Rent", business_profile="agency", company_size="small"),
        _row(4, category_name="Travel", business_profile="agency", company_size="small"),
        _row(5, category_name="Utilities", business_profile="growing_business", company_size="medium"),
        _row(6, category_name="Maintenance", business_profile="growing_business", company_size="medium"),
        _row(7, category_name="Food & Dining", business_profile="stable_company", company_size="small"),
        _row(8, category_name="Office Supplies", business_profile="stable_company", company_size="small"),
        _row(9, category_name="Professional Services", business_profile="small_business", company_size="micro"),
        _row(10, category_name="Transportation", business_profile="small_business", company_size="micro"),
    ]
    rows.append(_row(11, category_name="Income", category_type="income"))
    return rows


def test_budget_recommender_training_dataset_exists() -> None:
    assert DEFAULT_DATASET_PATH.exists()


def test_target_is_not_used_as_a_feature() -> None:
    assert TARGET_COLUMN not in FEATURE_COLUMNS


def test_prepare_training_data_excludes_leakage_columns_and_income_rows(tmp_path: Path) -> None:
    dataset_path = tmp_path / "budget.csv"
    rows = _sample_rows()
    for row in rows:
        row["raw_spike_amount"] = 9999.0
        row["future_budget_target"] = 1234.0
    _write_dataset(
        dataset_path,
        rows,
        extra_fieldnames=["raw_spike_amount", "future_budget_target"],
    )

    prepared = prepare_training_data(dataset_path)

    assert "recommended_budget" not in prepared.feature_columns
    assert "future_budget_target" in prepared.leakage_columns
    assert "raw_spike_amount" in prepared.leakage_columns
    assert "confidence_label" in prepared.excluded_columns
    assert "month" in prepared.excluded_columns
    assert prepared.filtered_income_rows == 1
    assert prepared.rows_used == len(rows) - 1
    assert all(row.category_name.lower() != "income" for row in prepared.rows)


def test_train_saves_artifact_with_required_components(tmp_path: Path) -> None:
    dataset_path = tmp_path / "budget.csv"
    model_path = tmp_path / "budget_recommender.joblib"
    _write_dataset(dataset_path, _sample_rows())

    train(dataset_path=dataset_path, model_path=model_path, cluster_count=3)

    assert model_path.exists()

    artifact = joblib.load(model_path)
    assert "regressor" in artifact
    assert "kmeans_model" in artifact
    assert "regressor_preprocessor" in artifact
    assert "cluster_preprocessor" in artifact
    assert "feature_columns" in artifact
    assert "runtime_feature_fields" in artifact
    assert "target_column" in artifact
    assert "cluster_summary" in artifact
    assert "metrics" in artifact
    assert artifact["target_column"] == TARGET_COLUMN
    assert artifact["metadata"]["model_family"] == MODEL_FAMILY
    assert artifact["metadata"]["algorithm"] == ALGORITHM


def test_budget_recommender_predictions_are_positive(tmp_path: Path) -> None:
    dataset_path = tmp_path / "budget.csv"
    model_path = tmp_path / "budget_recommender.joblib"
    _write_dataset(dataset_path, _sample_rows())

    artifact = train(dataset_path=dataset_path, model_path=model_path, cluster_count=3)
    prepared = prepare_training_data(dataset_path)
    predictions = artifact["regressor"].predict([row.features for row in prepared.rows])

    assert all(float(prediction) > 0 for prediction in predictions)
