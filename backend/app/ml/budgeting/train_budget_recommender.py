from __future__ import annotations

import argparse
import csv
import math
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import joblib
import numpy as np
from sklearn.cluster import KMeans
from sklearn.ensemble import RandomForestRegressor
from sklearn.feature_extraction import DictVectorizer
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler


DEFAULT_DATASET_PATH = (
    Path(__file__).resolve().parents[3]
    / "data"
    / "processed"
    / "bizmoneyai_budget_recommender.csv"
)
DEFAULT_MODEL_PATH = Path(__file__).resolve().parents[1] / "models" / "budget_recommender.joblib"

MODEL_NAME = "BizMoneyAI Model 4 Smart Budget Recommender"
MODEL_FAMILY = "smart_budget_recommender"
ALGORITHM = "RandomForestRegressor + KMeans"
RANDOM_STATE = 42
TARGET_COLUMN = "recommended_budget"

FEATURE_COLUMNS = [
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
    "category_name",
    "business_profile",
    "company_size",
]
CATEGORICAL_FEATURE_COLUMNS = [
    "category_name",
    "business_profile",
    "company_size",
]
NUMERIC_FEATURE_COLUMNS = [
    column for column in FEATURE_COLUMNS if column not in CATEGORICAL_FEATURE_COLUMNS
]
CLUSTER_FEATURE_COLUMNS = [
    "clean_monthly_spend",
    "current_budget",
    "avg_3_month_spend",
    "avg_6_month_spend",
    "growth_rate_3m",
    "budget_usage_ratio",
    "overspend_amount",
    "months_over_budget_3",
    "months_over_budget_6",
    "category_share_of_total",
    "total_clean_expense",
]
RUNTIME_FEATURE_FIELDS = [
    {
        "name": "clean_monthly_spend",
        "type": "float",
        "required": True,
        "description": "Clean category-level monthly spend with unusual spikes already removed.",
    },
    {
        "name": "current_budget",
        "type": "float",
        "required": True,
        "description": "Current budget assigned to the category for the active month.",
    },
    {
        "name": "previous_month_spend",
        "type": "float",
        "required": True,
        "description": "Previous month's clean spend for the same category.",
    },
    {
        "name": "prev_2_month_spend",
        "type": "float",
        "required": True,
        "description": "Clean spend from two months ago for the same category.",
    },
    {
        "name": "prev_3_month_spend",
        "type": "float",
        "required": True,
        "description": "Clean spend from three months ago for the same category.",
    },
    {
        "name": "avg_3_month_spend",
        "type": "float",
        "required": True,
        "description": "Rolling three-month clean spend average for the category.",
    },
    {
        "name": "avg_6_month_spend",
        "type": "float",
        "required": True,
        "description": "Rolling six-month clean spend average for the category.",
    },
    {
        "name": "growth_rate_3m",
        "type": "float",
        "required": True,
        "description": "Three-month category spending growth rate derived from clean spend history.",
    },
    {
        "name": "budget_usage_ratio",
        "type": "float",
        "required": True,
        "description": "Current clean spend divided by current budget.",
    },
    {
        "name": "overspend_amount",
        "type": "float",
        "required": True,
        "description": "Positive overspend gap between clean spend and current budget.",
    },
    {
        "name": "months_over_budget_3",
        "type": "float",
        "required": True,
        "description": "Count of months over budget in the recent three-month window.",
    },
    {
        "name": "months_over_budget_6",
        "type": "float",
        "required": True,
        "description": "Count of months over budget in the recent six-month window.",
    },
    {
        "name": "category_share_of_total",
        "type": "float",
        "required": True,
        "description": "Category share of total clean expense for the business.",
    },
    {
        "name": "total_clean_expense",
        "type": "float",
        "required": True,
        "description": "Total clean monthly expense across all expense categories.",
    },
    {
        "name": "category_name",
        "type": "string",
        "required": True,
        "description": "Expense category name.",
    },
    {
        "name": "business_profile",
        "type": "string",
        "required": True,
        "description": "Business behavior/profile segment used in the generated dataset.",
    },
    {
        "name": "company_size",
        "type": "string",
        "required": True,
        "description": "Company size bucket.",
    },
]

EXPLICIT_EXCLUDED_COLUMNS = {
    TARGET_COLUMN,
    "user_id",
    "month",
    "category_type",
    "confidence_label",
}
LEAKAGE_NAME_PARTS = (
    "future",
    "target",
    "label",
    "fraud",
    "unusual",
    "spike",
    "anomaly",
    "risk",
    "raw",
    "next_",
)
INCOME_NAME_PARTS = (
    "income",
    "revenue",
    "sales",
)
REQUIRED_COLUMNS = {TARGET_COLUMN, *FEATURE_COLUMNS}


@dataclass(frozen=True)
class BudgetTrainingRow:
    features: dict[str, float | str]
    target: float
    category_name: str
    business_profile: str
    company_size: str
    cluster_values: list[float]
    raw_row: dict[str, str]


@dataclass(frozen=True)
class PreparedBudgetDataset:
    dataset_path: Path
    source_rows: int
    rows_used: int
    filtered_non_expense_rows: int
    filtered_income_rows: int
    feature_columns: list[str]
    excluded_columns: list[str]
    leakage_columns: list[str]
    rows: list[BudgetTrainingRow]


def _safe_float(value: str | None, *, column: str) -> float:
    if value in (None, ""):
        raise ValueError(f"Missing numeric value for {column}")
    try:
        number = float(value)
    except ValueError as exc:
        raise ValueError(f"Invalid numeric value for {column}: {value!r}") from exc
    if math.isnan(number) or math.isinf(number):
        raise ValueError(f"Invalid numeric value for {column}: {value!r}")
    return number


def _string_value(row: dict[str, str], column: str) -> str:
    return (row.get(column) or "unknown").strip() or "unknown"


def _is_income_category(row: dict[str, str]) -> bool:
    category_type = _string_value(row, "category_type").lower()
    category_name = _string_value(row, "category_name").lower()
    if category_type == "income":
        return True
    return any(part in category_name for part in INCOME_NAME_PARTS)


def _is_non_expense_row(row: dict[str, str]) -> bool:
    if "category_type" not in row:
        return False
    category_type = _string_value(row, "category_type").lower()
    return category_type not in {"", "expense"}


def _excluded_columns(columns: list[str]) -> tuple[list[str], list[str]]:
    normalized = {column: column.lower() for column in columns}
    leakage_columns = sorted(
        {
            column
            for column in columns
            if column in EXPLICIT_EXCLUDED_COLUMNS
            or any(part in normalized[column] for part in LEAKAGE_NAME_PARTS)
        }
    )
    excluded_columns = sorted(
        {
            column
            for column in columns
            if column in EXPLICIT_EXCLUDED_COLUMNS or column in leakage_columns
        }
    )
    return excluded_columns, leakage_columns


def _validate_required_columns(fieldnames: list[str] | None, dataset_path: Path) -> list[str]:
    columns = list(fieldnames or [])
    missing = sorted(REQUIRED_COLUMNS - set(columns))
    if missing:
        raise RuntimeError(f"{dataset_path} is missing required columns: {', '.join(missing)}")
    return columns


def _row_to_training_row(row: dict[str, str]) -> BudgetTrainingRow:
    features: dict[str, float | str] = {}
    for column in NUMERIC_FEATURE_COLUMNS:
        features[column] = _safe_float(row.get(column), column=column)
    for column in CATEGORICAL_FEATURE_COLUMNS:
        features[column] = _string_value(row, column)

    return BudgetTrainingRow(
        features=features,
        target=_safe_float(row.get(TARGET_COLUMN), column=TARGET_COLUMN),
        category_name=_string_value(row, "category_name"),
        business_profile=_string_value(row, "business_profile"),
        company_size=_string_value(row, "company_size"),
        cluster_values=[_safe_float(row.get(column), column=column) for column in CLUSTER_FEATURE_COLUMNS],
        raw_row=row,
    )


def prepare_training_data(dataset_path: Path = DEFAULT_DATASET_PATH) -> PreparedBudgetDataset:
    if not dataset_path.exists():
        raise RuntimeError(f"Budget recommender dataset not found at {dataset_path}")

    with dataset_path.open("r", newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        columns = _validate_required_columns(reader.fieldnames, dataset_path)
        raw_rows = list(reader)

    excluded_columns, leakage_columns = _excluded_columns(columns)

    source_rows = len(raw_rows)
    filtered_non_expense_rows = 0
    filtered_income_rows = 0
    prepared_rows: list[BudgetTrainingRow] = []
    for row in raw_rows:
        if _is_income_category(row):
            filtered_income_rows += 1
            continue
        if _is_non_expense_row(row):
            filtered_non_expense_rows += 1
            continue
        prepared_rows.append(_row_to_training_row(row))

    if not prepared_rows:
        raise RuntimeError(f"No valid Model 4 training rows found in {dataset_path}")

    return PreparedBudgetDataset(
        dataset_path=dataset_path,
        source_rows=source_rows,
        rows_used=len(prepared_rows),
        filtered_non_expense_rows=filtered_non_expense_rows,
        filtered_income_rows=filtered_income_rows,
        feature_columns=list(FEATURE_COLUMNS),
        excluded_columns=excluded_columns,
        leakage_columns=leakage_columns,
        rows=prepared_rows,
    )


def _regressor_pipeline() -> Pipeline:
    return Pipeline(
        steps=[
            ("vectorizer", DictVectorizer(sparse=False)),
            (
                "regressor",
                RandomForestRegressor(
                    n_estimators=240,
                    min_samples_leaf=2,
                    random_state=RANDOM_STATE,
                    n_jobs=-1,
                ),
            ),
        ]
    )


def _cluster_pipeline(cluster_count: int) -> Pipeline:
    return Pipeline(
        steps=[
            ("scaler", StandardScaler()),
            (
                "kmeans",
                KMeans(
                    n_clusters=cluster_count,
                    n_init=20,
                    random_state=RANDOM_STATE,
                ),
            ),
        ]
    )


def _metrics(y_true: list[float], y_pred: list[float]) -> dict[str, float]:
    mae = float(mean_absolute_error(y_true, y_pred))
    rmse = float(math.sqrt(mean_squared_error(y_true, y_pred)))
    r2 = float(r2_score(y_true, y_pred))
    mape_values = [
        abs((actual - predicted) / actual)
        for actual, predicted in zip(y_true, y_pred, strict=True)
        if actual > 0
    ]
    return {
        "mae": round(mae, 4),
        "rmse": round(rmse, 4),
        "r2": round(r2, 4),
        "mape": round(sum(mape_values) / len(mape_values), 4) if mape_values else 0.0,
    }


def _cluster_summary(
    rows: list[BudgetTrainingRow],
    cluster_labels: np.ndarray,
) -> tuple[list[str], list[dict[str, Any]]]:
    summaries: list[dict[str, Any]] = []
    label_names: list[str] = []
    for cluster_id in sorted(set(int(label) for label in cluster_labels)):
        cluster_rows = [
            row for row, label in zip(rows, cluster_labels, strict=True) if int(label) == cluster_id
        ]
        label_name = f"behavior_cluster_{cluster_id}"
        label_names.append(label_name)
        category_counts = Counter(row.category_name for row in cluster_rows)
        profile_counts = Counter(row.business_profile for row in cluster_rows)
        summaries.append(
            {
                "cluster_id": cluster_id,
                "label": label_name,
                "row_count": len(cluster_rows),
                "top_category": category_counts.most_common(1)[0][0],
                "top_business_profile": profile_counts.most_common(1)[0][0],
                "avg_clean_monthly_spend": round(
                    sum(float(row.features["clean_monthly_spend"]) for row in cluster_rows) / len(cluster_rows),
                    2,
                ),
                "avg_current_budget": round(
                    sum(float(row.features["current_budget"]) for row in cluster_rows) / len(cluster_rows),
                    2,
                ),
                "avg_recommended_budget": round(
                    sum(row.target for row in cluster_rows) / len(cluster_rows),
                    2,
                ),
                "avg_budget_usage_ratio": round(
                    sum(float(row.features["budget_usage_ratio"]) for row in cluster_rows) / len(cluster_rows),
                    4,
                ),
            }
        )
    return label_names, summaries


def train(
    dataset_path: Path = DEFAULT_DATASET_PATH,
    model_path: Path = DEFAULT_MODEL_PATH,
    *,
    test_size: float = 0.20,
    cluster_count: int = 4,
) -> dict[str, Any]:
    prepared = prepare_training_data(dataset_path)
    rows = prepared.rows
    train_rows, test_rows = train_test_split(
        rows,
        test_size=test_size,
        random_state=RANDOM_STATE,
        shuffle=True,
    )

    x_train = [row.features for row in train_rows]
    y_train = [row.target for row in train_rows]
    x_test = [row.features for row in test_rows]
    y_test = [row.target for row in test_rows]

    evaluation_regressor = _regressor_pipeline()
    evaluation_regressor.fit(x_train, y_train)
    evaluation_predictions = [
        max(0.0, float(value))
        for value in evaluation_regressor.predict(x_test)
    ]
    metrics = _metrics(y_test, evaluation_predictions)

    final_regressor = _regressor_pipeline()
    final_regressor.fit([row.features for row in rows], [row.target for row in rows])

    effective_cluster_count = max(1, min(cluster_count, len(rows)))
    cluster_pipeline = _cluster_pipeline(effective_cluster_count)
    full_cluster_values = np.array([row.cluster_values for row in rows], dtype=np.float64)
    cluster_pipeline.fit(full_cluster_values)
    cluster_labels = cluster_pipeline.named_steps["kmeans"].labels_
    label_names, cluster_summary = _cluster_summary(rows, cluster_labels)

    sample_predictions: list[dict[str, Any]] = []
    for row, predicted in list(zip(test_rows, evaluation_predictions, strict=True))[:5]:
        sample_predictions.append(
            {
                "category_name": row.category_name,
                "business_profile": row.business_profile,
                "company_size": row.company_size,
                "actual": round(row.target, 2),
                "predicted": round(predicted, 2),
            }
        )

    artifact = {
        "regressor": final_regressor,
        "kmeans_model": cluster_pipeline.named_steps["kmeans"],
        "regressor_preprocessor": final_regressor.named_steps["vectorizer"],
        "cluster_preprocessor": cluster_pipeline.named_steps["scaler"],
        "cluster_pipeline": cluster_pipeline,
        "feature_columns": list(prepared.feature_columns),
        "cluster_feature_columns": list(CLUSTER_FEATURE_COLUMNS),
        "runtime_feature_fields": list(RUNTIME_FEATURE_FIELDS),
        "target_column": TARGET_COLUMN,
        "cluster_labels": label_names,
        "cluster_summary": cluster_summary,
        "metrics": metrics,
        "model_name": MODEL_NAME,
        "model_family": MODEL_FAMILY,
        "algorithm": ALGORITHM,
        "metadata": {
            "model_family": MODEL_FAMILY,
            "algorithm": ALGORITHM,
            "dataset_path": str(dataset_path),
            "rows_used": prepared.rows_used,
            "source_rows": prepared.source_rows,
            "filtered_non_expense_rows": prepared.filtered_non_expense_rows,
            "filtered_income_rows": prepared.filtered_income_rows,
            "train_rows": len(train_rows),
            "test_rows": len(test_rows),
            "feature_columns": list(prepared.feature_columns),
            "runtime_feature_fields": list(RUNTIME_FEATURE_FIELDS),
            "excluded_columns": list(prepared.excluded_columns),
            "leakage_columns": list(prepared.leakage_columns),
            "cluster_feature_columns": list(CLUSTER_FEATURE_COLUMNS),
            "cluster_count": effective_cluster_count,
            "trained_at": datetime.now(timezone.utc).isoformat(),
        },
    }

    model_path.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(artifact, model_path)

    print(f"Rows used: {prepared.rows_used}")
    print(f"Train rows: {len(train_rows)}")
    print(f"Test rows: {len(test_rows)}")
    print(f"Feature columns: {', '.join(prepared.feature_columns)}")
    print(f"MAE: {metrics['mae']:.4f}")
    print(f"RMSE: {metrics['rmse']:.4f}")
    print(f"R2: {metrics['r2']:.4f}")
    print(f"MAPE: {metrics['mape']:.4f}")
    print("Cluster summary:")
    for summary in cluster_summary:
        print(
            f"- {summary['label']}: rows={summary['row_count']} "
            f"top_category={summary['top_category']} "
            f"top_profile={summary['top_business_profile']} "
            f"avg_clean_spend={summary['avg_clean_monthly_spend']:.2f} "
            f"avg_current_budget={summary['avg_current_budget']:.2f} "
            f"avg_recommended_budget={summary['avg_recommended_budget']:.2f} "
            f"avg_budget_usage_ratio={summary['avg_budget_usage_ratio']:.4f}"
        )
    print("Sample predictions:")
    for sample in sample_predictions:
        print(
            f"- category={sample['category_name']} "
            f"profile={sample['business_profile']} "
            f"size={sample['company_size']} "
            f"actual={sample['actual']:.2f} "
            f"predicted={sample['predicted']:.2f}"
        )
    print(f"Saved Model 4 budget recommender to {model_path}")

    return artifact


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Train the BizMoneyAI Model 4 smart budget recommender.")
    parser.add_argument("--dataset-path", type=Path, default=DEFAULT_DATASET_PATH)
    parser.add_argument("--model-path", type=Path, default=DEFAULT_MODEL_PATH)
    parser.add_argument("--test-size", type=float, default=0.20)
    parser.add_argument("--cluster-count", type=int, default=4)
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    train(
        dataset_path=args.dataset_path,
        model_path=args.model_path,
        test_size=args.test_size,
        cluster_count=args.cluster_count,
    )
