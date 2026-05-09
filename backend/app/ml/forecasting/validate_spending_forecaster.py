from __future__ import annotations

import argparse
import csv
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import joblib
from sklearn.metrics import mean_absolute_error, r2_score

from app.ml.forecasting.train_spending_forecaster import (
    CATEGORICAL_FEATURE_COLUMNS,
    DEFAULT_DATASET_PATH,
    DEFAULT_MODEL_PATH,
    FORBIDDEN_FEATURE_COLUMNS,
    MODEL_FAMILY,
    TARGET_COLUMN,
    _parse_date,
    _validate_clean_lag_features,
    _validate_clean_targets,
)

EXPLICIT_LEAKAGE_COLUMNS = {
    TARGET_COLUMN,
    "raw_next_month_expense",
    "raw_next_month_total_expense",
    "next_month_raw_expense",
    "next_month_raw_total_expense",
    *FORBIDDEN_FEATURE_COLUMNS,
}

LEAKAGE_NAME_PARTS = (
    "fraud",
    "unusual",
    "outlier",
    "anomaly",
    "risk_score",
    "risk_level",
    "raw_total_expense",
    "raw_next_month",
)


@dataclass(frozen=True)
class ForecastValidationRecord:
    user_id: str
    month_start: str
    features: dict[str, float | str]
    target: float
    raw_row: dict[str, str]


@dataclass(frozen=True)
class ForecastPrediction:
    user_id: str
    month_start: str
    actual: float
    predicted: float
    absolute_error: float
    clean_total_expense: float
    raw_total_expense: float | None
    excluded_unusual_expense: float


@dataclass(frozen=True)
class ForecastValidationResult:
    model_path: Path
    dataset_path: Path
    model_name: str | None
    model_family: str | None
    target_column: str
    feature_columns: list[str]
    forbidden_columns: list[str]
    metrics: dict[str, float | None]
    evaluated_rows: int
    examples: list[ForecastPrediction]
    sanity_examples: dict[str, ForecastPrediction | None]
    clean_spending_confirmed: bool


def _safe_float(value: str | None, *, default: float | None = None) -> float | None:
    if value in (None, ""):
        return default
    try:
        number = float(str(value).replace(",", ""))
    except ValueError:
        return default
    if math.isnan(number) or math.isinf(number):
        return default
    return number


def _required_float(row: dict[str, str], column: str) -> float:
    value = _safe_float(row.get(column))
    if value is None:
        raise ValueError(f"Missing or invalid numeric value for {column}")
    return value


def _is_leakage_column(column: str) -> bool:
    normalized = column.strip().lower()
    if normalized in EXPLICIT_LEAKAGE_COLUMNS:
        return True
    return any(part in normalized for part in LEAKAGE_NAME_PARTS)


def load_forecaster_artifact(model_path: Path = DEFAULT_MODEL_PATH) -> dict[str, Any]:
    if not model_path.exists():
        raise RuntimeError(f"Model 3 artifact not found at {model_path}")

    try:
        artifact = joblib.load(model_path)
    except Exception as exc:
        raise RuntimeError(f"Failed to load Model 3 artifact at {model_path}") from exc

    if not isinstance(artifact, dict):
        raise RuntimeError("Model 3 artifact must be a dictionary")

    model = artifact.get("model")
    if model is None or not hasattr(model, "predict"):
        raise RuntimeError("Model 3 artifact does not contain a predict-capable model")

    feature_columns = artifact.get("feature_columns")
    if not isinstance(feature_columns, list) or not all(isinstance(item, str) for item in feature_columns):
        raise RuntimeError("Model 3 artifact must contain a string feature_columns list")

    target_column = artifact.get("target_column")
    if not isinstance(target_column, str) or not target_column:
        raise RuntimeError("Model 3 artifact must contain a target_column")

    model_family = artifact.get("model_family")
    if model_family not in {None, MODEL_FAMILY}:
        raise RuntimeError(f"Unsupported Model 3 artifact family: {model_family}")

    return artifact


def load_forecast_rows(dataset_path: Path = DEFAULT_DATASET_PATH) -> list[dict[str, str]]:
    if not dataset_path.exists():
        raise RuntimeError(f"Model 3 validation dataset not found at {dataset_path}")

    with dataset_path.open("r", newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        rows = [row for row in reader if row.get(TARGET_COLUMN, "").strip()]

    if not rows:
        raise RuntimeError(f"No Model 3 validation rows found in {dataset_path}")
    return rows


def validate_artifact_feature_contract(artifact: dict[str, Any], rows: list[dict[str, str]]) -> None:
    feature_columns = list(artifact["feature_columns"])
    target_column = str(artifact["target_column"])
    dataset_columns = set(rows[0].keys())

    leakage_columns = sorted(column for column in feature_columns if _is_leakage_column(column))
    if leakage_columns:
        raise RuntimeError(f"Model 3 artifact uses forbidden leakage columns: {', '.join(leakage_columns)}")

    normalized_target = target_column.lower()
    if "raw" in normalized_target or "fraud" in normalized_target or "unusual" in normalized_target:
        raise RuntimeError(f"Model 3 target column must be clean spending, got {target_column}")

    missing_columns = sorted(column for column in [*feature_columns, target_column] if column not in dataset_columns)
    if missing_columns:
        raise RuntimeError(f"Model 3 validation dataset is missing columns: {', '.join(missing_columns)}")

    _validate_clean_targets(rows)
    _validate_clean_lag_features(rows)


def _record_from_row(row: dict[str, str], feature_columns: list[str], target_column: str) -> ForecastValidationRecord:
    features: dict[str, float | str] = {}
    categorical_columns = set(CATEGORICAL_FEATURE_COLUMNS)
    for column in feature_columns:
        if column in categorical_columns:
            features[column] = (row.get(column) or "unknown").strip() or "unknown"
        else:
            features[column] = _required_float(row, column)

    return ForecastValidationRecord(
        user_id=str(row.get("user_id") or ""),
        month_start=str(row.get("month_start") or ""),
        features=features,
        target=_required_float(row, target_column),
        raw_row=row,
    )


def _records_from_rows(
    rows: list[dict[str, str]],
    *,
    feature_columns: list[str],
    target_column: str,
) -> list[ForecastValidationRecord]:
    return [_record_from_row(row, feature_columns, target_column) for row in rows]


def _evaluation_records(
    records: list[ForecastValidationRecord],
    artifact: dict[str, Any],
) -> list[ForecastValidationRecord]:
    metadata = artifact.get("metadata") if isinstance(artifact.get("metadata"), dict) else {}
    test_rows = metadata.get("test_rows")
    if not isinstance(test_rows, int) or test_rows <= 0:
        return records

    ordered = sorted(
        records,
        key=lambda record: (_parse_date(record.month_start, column="month_start"), record.user_id),
    )
    return ordered[-min(test_rows, len(ordered)) :]


def _metrics(actuals: list[float], predictions: list[float]) -> dict[str, float | None]:
    mae = float(mean_absolute_error(actuals, predictions))
    rmse = math.sqrt(sum((actual - predicted) ** 2 for actual, predicted in zip(actuals, predictions, strict=True)) / len(actuals))
    r2 = float(r2_score(actuals, predictions)) if len(actuals) >= 2 else None
    positive_actuals = [actual for actual in actuals if actual > 0]
    if len(positive_actuals) == len(actuals):
        mape = sum(
            abs((actual - predicted) / actual)
            for actual, predicted in zip(actuals, predictions, strict=True)
        ) / len(actuals)
    else:
        mape = None

    return {
        "mae": round(mae, 4),
        "rmse": round(float(rmse), 4),
        "r2": round(r2, 4) if r2 is not None else None,
        "mape": round(float(mape), 4) if mape is not None else None,
    }


def _prediction(record: ForecastValidationRecord, predicted: float) -> ForecastPrediction:
    prediction_value = max(0.0, float(predicted))
    raw_total = _safe_float(record.raw_row.get("raw_total_expense"))
    excluded_unusual = _safe_float(record.raw_row.get("excluded_unusual_expense"), default=0.0) or 0.0
    clean_total = _required_float(record.raw_row, "clean_total_expense")
    return ForecastPrediction(
        user_id=record.user_id,
        month_start=record.month_start,
        actual=record.target,
        predicted=prediction_value,
        absolute_error=abs(record.target - prediction_value),
        clean_total_expense=clean_total,
        raw_total_expense=raw_total,
        excluded_unusual_expense=excluded_unusual,
    )


def _select_sanity_examples(
    records: list[ForecastValidationRecord],
    predictions_by_key: dict[tuple[str, str], ForecastPrediction],
) -> dict[str, ForecastPrediction | None]:
    def prediction_for(record: ForecastValidationRecord | None) -> ForecastPrediction | None:
        if record is None:
            return None
        return predictions_by_key.get((record.user_id, record.month_start))

    stable_record = min(
        records,
        key=lambda record: abs(_safe_float(record.raw_row.get("expense_growth_rate"), default=0.0) or 0.0),
        default=None,
    )
    increasing_record = max(
        records,
        key=lambda record: _safe_float(record.raw_row.get("expense_growth_rate"), default=-999.0) or -999.0,
        default=None,
    )
    budget_heavy_record = max(
        records,
        key=lambda record: _safe_float(record.raw_row.get("budget_usage_ratio"), default=-1.0) or -1.0,
        default=None,
    )
    unusual_record = next(
        (
            record
            for record in records
            if (_safe_float(record.raw_row.get("excluded_unusual_expense"), default=0.0) or 0.0) > 0
        ),
        None,
    )

    return {
        "stable_spending_user": prediction_for(stable_record),
        "increasing_spending_user": prediction_for(increasing_record),
        "budget_heavy_user": prediction_for(budget_heavy_record),
        "user_with_excluded_unusual_expense": prediction_for(unusual_record),
    }


def validate_spending_forecaster(
    model_path: Path = DEFAULT_MODEL_PATH,
    dataset_path: Path = DEFAULT_DATASET_PATH,
    *,
    example_count: int = 8,
) -> ForecastValidationResult:
    artifact = load_forecaster_artifact(model_path)
    rows = load_forecast_rows(dataset_path)
    validate_artifact_feature_contract(artifact, rows)

    feature_columns = list(artifact["feature_columns"])
    target_column = str(artifact["target_column"])
    records = _records_from_rows(rows, feature_columns=feature_columns, target_column=target_column)
    evaluation_records = _evaluation_records(records, artifact)

    model = artifact["model"]
    raw_predictions = [float(value) for value in model.predict([record.features for record in evaluation_records])]
    predictions = [_prediction(record, predicted) for record, predicted in zip(evaluation_records, raw_predictions, strict=True)]
    actuals = [record.target for record in evaluation_records]
    clipped_predictions = [prediction.predicted for prediction in predictions]
    metrics = _metrics(actuals, clipped_predictions)

    predictions_by_key = {
        (prediction.user_id, prediction.month_start): prediction
        for prediction in predictions
    }

    return ForecastValidationResult(
        model_path=model_path,
        dataset_path=dataset_path,
        model_name=artifact.get("model_name"),
        model_family=artifact.get("model_family"),
        target_column=target_column,
        feature_columns=feature_columns,
        forbidden_columns=sorted(EXPLICIT_LEAKAGE_COLUMNS | set(FORBIDDEN_FEATURE_COLUMNS)),
        metrics=metrics,
        evaluated_rows=len(evaluation_records),
        examples=predictions[:example_count],
        sanity_examples=_select_sanity_examples(evaluation_records, predictions_by_key),
        clean_spending_confirmed=True,
    )


def _format_money(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value:,.2f}"


def print_validation_report(result: ForecastValidationResult) -> None:
    print("BizMoneyAI Model 3 Spending Forecaster Validation")
    print(f"Artifact: {result.model_path}")
    print(f"Dataset: {result.dataset_path}")
    print(f"Model name: {result.model_name or 'unknown'}")
    print(f"Model family: {result.model_family or 'unknown'}")
    print(f"Target column: {result.target_column}")
    print(f"Evaluated rows: {result.evaluated_rows}")
    print(f"Feature columns: {', '.join(result.feature_columns)}")
    print("Forbidden leakage columns are not used: OK")
    print("Clean spending behavior confirmed: OK")
    print("Metrics:")
    print(f"- MAE: {result.metrics['mae']}")
    print(f"- RMSE: {result.metrics['rmse']}")
    print(f"- R2: {result.metrics['r2']}")
    print(f"- MAPE: {result.metrics['mape'] if result.metrics['mape'] is not None else 'n/a'}")

    print("Example predictions:")
    for example in result.examples:
        print(
            f"- user={example.user_id} month={example.month_start} "
            f"actual={_format_money(example.actual)} "
            f"predicted={_format_money(example.predicted)} "
            f"abs_error={_format_money(example.absolute_error)}"
        )

    print("Sanity examples:")
    for label, example in result.sanity_examples.items():
        if example is None:
            print(f"- {label}: n/a")
            continue
        print(
            f"- {label}: user={example.user_id} month={example.month_start} "
            f"actual={_format_money(example.actual)} "
            f"predicted={_format_money(example.predicted)} "
            f"abs_error={_format_money(example.absolute_error)} "
            f"clean_current={_format_money(example.clean_total_expense)} "
            f"raw_current={_format_money(example.raw_total_expense)} "
            f"excluded_unusual={_format_money(example.excluded_unusual_expense)}"
        )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate the BizMoneyAI Model 3 spending forecaster.")
    parser.add_argument("--model-path", type=Path, default=DEFAULT_MODEL_PATH)
    parser.add_argument("--dataset-path", type=Path, default=DEFAULT_DATASET_PATH)
    parser.add_argument("--examples", type=int, default=8)
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    validation_result = validate_spending_forecaster(
        model_path=args.model_path,
        dataset_path=args.dataset_path,
        example_count=args.examples,
    )
    print_validation_report(validation_result)
