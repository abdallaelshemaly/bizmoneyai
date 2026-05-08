from __future__ import annotations

import argparse
import csv
import math
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import joblib
from sklearn.ensemble import RandomForestRegressor
from sklearn.feature_extraction import DictVectorizer
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from sklearn.pipeline import Pipeline

DEFAULT_DATASET_PATH = (
    Path(__file__).resolve().parents[3]
    / "data"
    / "processed"
    / "bizmoneyai_spending_forecast.csv"
)
DEFAULT_MODEL_PATH = Path(__file__).resolve().parents[1] / "models" / "spending_forecaster.joblib"

MODEL_NAME = "BizMoneyAI Model 3 Spending Forecaster"
MODEL_FAMILY = "bizmoneyai_spending_forecast"
RANDOM_STATE = 42
TARGET_COLUMN = "next_month_total_expense"

CLEAN_SPENDING_FEATURE_COLUMNS = [
    "clean_total_expense",
    "previous_month_expense",
    "expense_2_months_ago",
    "rolling_3_month_expense_avg",
    "rolling_6_month_expense_avg",
    "expense_growth_rate",
    "expense_to_income_ratio",
    "budget_usage_ratio",
]

CONTEXT_NUMERIC_FEATURE_COLUMNS = [
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
]

CATEGORICAL_FEATURE_COLUMNS = [
    "business_profile",
    "top_spend_category_1",
    "top_spend_category_2",
    "top_spend_category_3",
]

FEATURE_COLUMNS = (
    CLEAN_SPENDING_FEATURE_COLUMNS
    + CONTEXT_NUMERIC_FEATURE_COLUMNS
    + CATEGORICAL_FEATURE_COLUMNS
)

FORBIDDEN_FEATURE_COLUMNS = {
    "raw_total_expense",
    "excluded_unusual_expense",
    "max_expense_amount",
}

REQUIRED_COLUMNS = {
    "user_id",
    "month_start",
    "clean_total_expense",
    TARGET_COLUMN,
    *FEATURE_COLUMNS,
}


@dataclass(frozen=True)
class TrainingRecord:
    user_id: str
    month_start: date
    features: dict[str, float | str]
    target: float


def _parse_date(value: str, *, column: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"Invalid {column} value {value!r}") from exc


def _add_one_month(value: date) -> date:
    if value.month == 12:
        return date(value.year + 1, 1, 1)
    return date(value.year, value.month + 1, 1)


def _float_value(row: dict[str, str], column: str) -> float:
    raw_value = row.get(column, "")
    if raw_value == "":
        raise ValueError(f"Missing numeric value for {column}")
    try:
        number = float(raw_value)
    except ValueError as exc:
        raise ValueError(f"Invalid numeric value for {column}: {raw_value!r}") from exc
    if math.isnan(number) or math.isinf(number):
        raise ValueError(f"Invalid numeric value for {column}: {raw_value!r}")
    return number


def _feature_dict(row: dict[str, str]) -> dict[str, float | str]:
    features: dict[str, float | str] = {}
    for column in CLEAN_SPENDING_FEATURE_COLUMNS + CONTEXT_NUMERIC_FEATURE_COLUMNS:
        features[column] = _float_value(row, column)
    for column in CATEGORICAL_FEATURE_COLUMNS:
        features[column] = (row.get(column) or "unknown").strip() or "unknown"
    return features


def _validate_feature_policy() -> None:
    forbidden = sorted(set(FEATURE_COLUMNS) & FORBIDDEN_FEATURE_COLUMNS)
    if forbidden:
        raise RuntimeError(f"Model 3 feature policy forbids these columns: {', '.join(forbidden)}")
    if "clean_total_expense" not in FEATURE_COLUMNS:
        raise RuntimeError("Model 3 must train with clean_total_expense")


def _validate_required_columns(fieldnames: list[str] | None, dataset_path: Path) -> None:
    present = set(fieldnames or [])
    missing = sorted(REQUIRED_COLUMNS - present)
    if missing:
        raise RuntimeError(f"{dataset_path} is missing required columns: {', '.join(missing)}")


def _validate_clean_targets(rows: list[dict[str, str]]) -> None:
    rows_by_user_month: dict[tuple[str, date], dict[str, str]] = {}
    for row in rows:
        user_id = str(row["user_id"]).strip()
        month_start = _parse_date(row["month_start"], column="month_start")
        rows_by_user_month[(user_id, month_start)] = row

    failures: list[str] = []
    for row in rows:
        user_id = str(row["user_id"]).strip()
        month_start = _parse_date(row["month_start"], column="month_start")
        next_row = rows_by_user_month.get((user_id, _add_one_month(month_start)))
        if next_row is None:
            continue

        target = _float_value(row, TARGET_COLUMN)
        next_clean = _float_value(next_row, "clean_total_expense")
        if abs(target - next_clean) <= 0.05:
            continue

        next_excluded = (
            _float_value(next_row, "excluded_unusual_expense")
            if "excluded_unusual_expense" in next_row
            else 0.0
        )
        if next_excluded > 0:
            next_raw = (
                _float_value(next_row, "raw_total_expense")
                if "raw_total_expense" in next_row
                else 0.0
            )
            failures.append(
                f"{user_id} {month_start.isoformat()} target={target:.2f} "
                f"next_clean={next_clean:.2f} next_raw={next_raw:.2f}"
            )
        else:
            failures.append(
                f"{user_id} {month_start.isoformat()} target={target:.2f} next_clean={next_clean:.2f}"
            )

    if failures:
        sample = "; ".join(failures[:5])
        raise RuntimeError(
            "Model 3 target must be next month's clean_total_expense, not raw_total_expense. "
            f"Examples: {sample}"
        )


def _validate_clean_lag_features(rows: list[dict[str, str]]) -> None:
    rows_by_user: dict[str, list[dict[str, str]]] = {}
    for row in rows:
        rows_by_user.setdefault(str(row["user_id"]).strip(), []).append(row)

    failures: list[str] = []
    for user_rows in rows_by_user.values():
        ordered = sorted(
            user_rows,
            key=lambda item: _parse_date(item["month_start"], column="month_start"),
        )
        for index, row in enumerate(ordered):
            month_start = _parse_date(row["month_start"], column="month_start")
            previous_month_start = (
                _parse_date(ordered[index - 1]["month_start"], column="month_start")
                if index >= 1
                else None
            )
            two_months_ago_start = (
                _parse_date(ordered[index - 2]["month_start"], column="month_start")
                if index >= 2
                else None
            )
            has_previous_month = previous_month_start is not None and _add_one_month(previous_month_start) == month_start
            has_two_months_ago = (
                has_previous_month
                and two_months_ago_start is not None
                and _add_one_month(two_months_ago_start) == previous_month_start
            )

            if has_previous_month:
                expected_previous = _float_value(ordered[index - 1], "clean_total_expense")
                actual_previous = _float_value(row, "previous_month_expense")
                if abs(actual_previous - expected_previous) > 0.05:
                    failures.append(
                        f"{row['user_id']} {row['month_start']} previous_month_expense="
                        f"{actual_previous:.2f} expected_clean={expected_previous:.2f}"
                    )
            if has_two_months_ago:
                expected_two_months_ago = _float_value(ordered[index - 2], "clean_total_expense")
                actual_two_months_ago = _float_value(row, "expense_2_months_ago")
                if abs(actual_two_months_ago - expected_two_months_ago) > 0.05:
                    failures.append(
                        f"{row['user_id']} {row['month_start']} expense_2_months_ago="
                        f"{actual_two_months_ago:.2f} expected_clean={expected_two_months_ago:.2f}"
                    )

    if failures:
        sample = "; ".join(failures[:5])
        raise RuntimeError(f"Model 3 historical spending features must be clean. Examples: {sample}")


def load_training_records(dataset_path: Path = DEFAULT_DATASET_PATH) -> list[TrainingRecord]:
    _validate_feature_policy()
    with dataset_path.open("r", newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        _validate_required_columns(reader.fieldnames, dataset_path)
        rows = [row for row in reader if row.get(TARGET_COLUMN, "").strip()]

    if not rows:
        raise RuntimeError(f"No Model 3 training rows found in {dataset_path}")

    _validate_clean_targets(rows)
    _validate_clean_lag_features(rows)

    return [
        TrainingRecord(
            user_id=str(row["user_id"]).strip(),
            month_start=_parse_date(row["month_start"], column="month_start"),
            features=_feature_dict(row),
            target=_float_value(row, TARGET_COLUMN),
        )
        for row in rows
    ]


def _time_ordered_split(
    records: list[TrainingRecord],
    test_fraction: float,
) -> tuple[list[TrainingRecord], list[TrainingRecord]]:
    ordered = sorted(records, key=lambda record: (record.month_start, record.user_id))
    split_index = int(len(ordered) * (1.0 - test_fraction))
    split_index = max(1, min(split_index, len(ordered) - 1))
    return ordered[:split_index], ordered[split_index:]


def _metrics(y_true: list[float], y_pred: list[float]) -> dict[str, float]:
    mae = float(mean_absolute_error(y_true, y_pred))
    rmse = float(math.sqrt(mean_squared_error(y_true, y_pred)))
    r2 = float(r2_score(y_true, y_pred))
    mean_target = sum(y_true) / len(y_true)
    return {
        "mae": round(mae, 4),
        "rmse": round(rmse, 4),
        "r2": round(r2, 4),
        "mae_pct_of_mean_target": round(mae / mean_target, 4) if mean_target else 0.0,
    }


def train(
    dataset_path: Path = DEFAULT_DATASET_PATH,
    model_path: Path = DEFAULT_MODEL_PATH,
    *,
    test_fraction: float = 0.20,
) -> dict[str, Any]:
    records = load_training_records(dataset_path)
    train_records, test_records = _time_ordered_split(records, test_fraction)

    pipeline = Pipeline(
        steps=[
            ("features", DictVectorizer(sparse=False)),
            (
                "regressor",
                RandomForestRegressor(
                    n_estimators=180,
                    min_samples_leaf=3,
                    random_state=RANDOM_STATE,
                    n_jobs=-1,
                ),
            ),
        ]
    )

    train_features = [record.features for record in train_records]
    train_targets = [record.target for record in train_records]
    test_features = [record.features for record in test_records]
    test_targets = [record.target for record in test_records]

    pipeline.fit(train_features, train_targets)
    predictions = [float(value) for value in pipeline.predict(test_features)]
    evaluation = _metrics(test_targets, predictions)

    artifact = {
        "model": pipeline,
        "model_name": MODEL_NAME,
        "model_family": MODEL_FAMILY,
        "target_column": TARGET_COLUMN,
        "feature_columns": FEATURE_COLUMNS,
        "clean_spending_feature_columns": CLEAN_SPENDING_FEATURE_COLUMNS,
        "forbidden_feature_columns": sorted(FORBIDDEN_FEATURE_COLUMNS),
        "metadata": {
            "dataset_path": str(dataset_path),
            "train_rows": len(train_records),
            "test_rows": len(test_records),
            "test_fraction": test_fraction,
            "metrics": evaluation,
            "trained_at": datetime.now(timezone.utc).isoformat(),
            "clean_spending_policy": (
                "Forecast training uses clean_total_expense plus clean historical spending "
                "lags and excludes raw_total_expense, excluded_unusual_expense, and raw "
                "max expense spikes."
            ),
        },
    }

    model_path.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(artifact, model_path)

    print(f"Rows: {len(records)}")
    print(f"Train rows: {len(train_records)}")
    print(f"Test rows: {len(test_records)}")
    print(f"Features: {', '.join(FEATURE_COLUMNS)}")
    print(f"Target: {TARGET_COLUMN} (next month's clean_total_expense)")
    print(
        "Metrics: "
        f"MAE={evaluation['mae']:.4f}, "
        f"RMSE={evaluation['rmse']:.4f}, "
        f"R2={evaluation['r2']:.4f}, "
        f"MAE/mean={evaluation['mae_pct_of_mean_target']:.4f}"
    )
    print(f"Saved Model 3 spending forecaster to {model_path}")

    return artifact


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Train the BizMoneyAI Model 3 spending forecaster.")
    parser.add_argument("--dataset-path", type=Path, default=DEFAULT_DATASET_PATH)
    parser.add_argument("--model-path", type=Path, default=DEFAULT_MODEL_PATH)
    parser.add_argument("--test-fraction", type=float, default=0.20)
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    train(args.dataset_path, args.model_path, test_fraction=args.test_fraction)
