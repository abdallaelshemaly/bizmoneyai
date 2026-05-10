from __future__ import annotations

import argparse
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import joblib
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score

try:
    from .train_budget_recommender import (
        CLUSTER_FEATURE_COLUMNS,
        DEFAULT_DATASET_PATH,
        DEFAULT_MODEL_PATH,
        FEATURE_COLUMNS,
        MODEL_FAMILY,
        TARGET_COLUMN,
        prepare_training_data,
    )
except ImportError:
    from train_budget_recommender import (  # type: ignore[no-redef]
        CLUSTER_FEATURE_COLUMNS,
        DEFAULT_DATASET_PATH,
        DEFAULT_MODEL_PATH,
        FEATURE_COLUMNS,
        MODEL_FAMILY,
        TARGET_COLUMN,
        prepare_training_data,
    )


EXPECTED_MODEL_FAMILY = "smart_budget_recommender"
REQUIRED_ARTIFACT_KEYS = {
    "regressor",
    "feature_columns",
    "target_column",
    "cluster_summary",
    "metadata",
}


@dataclass(frozen=True)
class ScenarioResult:
    name: str
    category_name: str
    current_budget: float
    recommended_budget: float
    expected_change_amount: float
    expected_change_percent: float
    cluster_label: str
    reason: str
    raw_prediction: float


@dataclass(frozen=True)
class ValidationResult:
    model_path: Path
    dataset_path: Path
    dataset_rows: int
    feature_columns: list[str]
    runtime_feature_fields: list[dict[str, Any]]
    metrics: dict[str, float]
    scenario_results: list[ScenarioResult]
    weak_behaviors: list[str]
    cluster_summary: list[dict[str, Any]]


def _safe_float(value: Any) -> float:
    number = float(value)
    if math.isnan(number) or math.isinf(number):
        raise ValueError(f"Invalid numeric value: {value!r}")
    return number


def load_artifact(model_path: Path = DEFAULT_MODEL_PATH) -> dict[str, Any]:
    if not model_path.exists():
        raise RuntimeError(f"Model 4 artifact not found at {model_path}")

    artifact = joblib.load(model_path)
    if not isinstance(artifact, dict):
        raise RuntimeError("Model 4 artifact must be a dictionary")

    missing_keys = sorted(REQUIRED_ARTIFACT_KEYS - set(artifact.keys()))
    if missing_keys:
        raise RuntimeError(f"Model 4 artifact is missing keys: {', '.join(missing_keys)}")

    return artifact


def validate_artifact_contract(artifact: dict[str, Any]) -> list[dict[str, Any]]:
    model_family = artifact.get("model_family")
    if model_family != EXPECTED_MODEL_FAMILY:
        raise RuntimeError(f"Expected model_family={EXPECTED_MODEL_FAMILY}, got {model_family!r}")

    feature_columns = artifact.get("feature_columns")
    if not isinstance(feature_columns, list) or not feature_columns or not all(isinstance(item, str) for item in feature_columns):
        raise RuntimeError("Model 4 artifact must contain a non-empty string feature_columns list")

    if artifact.get("target_column") != TARGET_COLUMN:
        raise RuntimeError(f"Expected target_column={TARGET_COLUMN}, got {artifact.get('target_column')!r}")

    if TARGET_COLUMN in feature_columns:
        raise RuntimeError(f"Target leakage detected: {TARGET_COLUMN} is inside feature_columns")

    runtime_feature_fields = artifact.get("runtime_feature_fields")
    if runtime_feature_fields is None:
        metadata = artifact.get("metadata")
        if isinstance(metadata, dict):
            runtime_feature_fields = metadata.get("runtime_feature_fields")
    if not isinstance(runtime_feature_fields, list) or not runtime_feature_fields:
        raise RuntimeError("Model 4 artifact must document runtime_feature_fields")

    documented_feature_names = [field.get("name") for field in runtime_feature_fields if isinstance(field, dict)]
    if documented_feature_names != feature_columns:
        raise RuntimeError("runtime_feature_fields must match feature_columns in order")

    cluster_feature_columns = artifact.get("cluster_feature_columns")
    if not isinstance(cluster_feature_columns, list) or not cluster_feature_columns:
        raise RuntimeError("Model 4 artifact must contain cluster_feature_columns")

    for column in cluster_feature_columns:
        if column not in feature_columns:
            raise RuntimeError(f"Cluster feature column {column!r} is not present in feature_columns")

    return runtime_feature_fields


def _feature_row(**values: Any) -> dict[str, float | str]:
    row = {column: values[column] for column in FEATURE_COLUMNS}
    return row


def _stable_rent_scenario() -> tuple[str, dict[str, float | str], str]:
    return (
        "Scenario A: Stable Rent",
        _feature_row(
            clean_monthly_spend=2500.0,
            current_budget=3000.0,
            previous_month_spend=2485.0,
            prev_2_month_spend=2510.0,
            prev_3_month_spend=2495.0,
            avg_3_month_spend=2498.33,
            avg_6_month_spend=2502.50,
            growth_rate_3m=0.0020,
            budget_usage_ratio=0.8333,
            overspend_amount=0.0,
            months_over_budget_3=0.0,
            months_over_budget_6=0.0,
            category_share_of_total=0.21,
            total_clean_expense=12000.0,
            category_name="Rent",
            business_profile="stable_company",
            company_size="small",
        ),
        "Stable clean rent history with budget already above spend should stay close instead of jumping.",
    )


def _growing_marketing_scenario() -> tuple[str, dict[str, float | str], str]:
    return (
        "Scenario B: Growing Marketing",
        _feature_row(
            clean_monthly_spend=1800.0,
            current_budget=1200.0,
            previous_month_spend=1450.0,
            prev_2_month_spend=1200.0,
            prev_3_month_spend=950.0,
            avg_3_month_spend=1483.33,
            avg_6_month_spend=1320.00,
            growth_rate_3m=0.8947,
            budget_usage_ratio=1.5000,
            overspend_amount=600.0,
            months_over_budget_3=3.0,
            months_over_budget_6=5.0,
            category_share_of_total=0.22,
            total_clean_expense=9000.0,
            category_name="Marketing",
            business_profile="growing_business",
            company_size="medium",
        ),
        "Rapid clean spend growth and repeated overspending should push the recommendation upward.",
    )


def _overbudget_software_scenario() -> tuple[str, dict[str, float | str], str]:
    return (
        "Scenario C: Software Repeatedly Over Budget",
        _feature_row(
            clean_monthly_spend=950.0,
            current_budget=700.0,
            previous_month_spend=910.0,
            prev_2_month_spend=880.0,
            prev_3_month_spend=860.0,
            avg_3_month_spend=913.33,
            avg_6_month_spend=892.50,
            growth_rate_3m=0.1047,
            budget_usage_ratio=1.3571,
            overspend_amount=250.0,
            months_over_budget_3=3.0,
            months_over_budget_6=4.0,
            category_share_of_total=0.12,
            total_clean_expense=7600.0,
            category_name="Software",
            business_profile="lean_startup",
            company_size="micro",
        ),
        "Repeated moderate overruns should increase the budget, but not explode beyond the spending pattern.",
    )


def _stable_office_supplies_scenario() -> tuple[str, dict[str, float | str], str]:
    return (
        "Scenario D: Office Supplies Stable Small Spend",
        _feature_row(
            clean_monthly_spend=140.0,
            current_budget=220.0,
            previous_month_spend=135.0,
            prev_2_month_spend=145.0,
            prev_3_month_spend=130.0,
            avg_3_month_spend=140.00,
            avg_6_month_spend=142.00,
            growth_rate_3m=0.0769,
            budget_usage_ratio=0.6364,
            overspend_amount=0.0,
            months_over_budget_3=0.0,
            months_over_budget_6=0.0,
            category_share_of_total=0.02,
            total_clean_expense=4800.0,
            category_name="Office Supplies",
            business_profile="stable_company",
            company_size="small",
        ),
        "A small stable category should stay low and should not receive a bloated budget.",
    )


def _unusual_spike_excluded_scenario() -> tuple[str, dict[str, float | str], str]:
    return (
        "Scenario E: Unusual Spike Excluded",
        _feature_row(
            clean_monthly_spend=420.0,
            current_budget=450.0,
            previous_month_spend=430.0,
            prev_2_month_spend=410.0,
            prev_3_month_spend=425.0,
            avg_3_month_spend=420.00,
            avg_6_month_spend=418.00,
            growth_rate_3m=-0.0118,
            budget_usage_ratio=0.9333,
            overspend_amount=0.0,
            months_over_budget_3=0.0,
            months_over_budget_6=0.0,
            category_share_of_total=0.04,
            total_clean_expense=6000.0,
            category_name="Travel",
            business_profile="agency",
            company_size="small",
        ),
        "A raw spike is assumed to have been removed already, so the recommendation should stay grounded in clean spend.",
    )


def scenario_inputs() -> list[tuple[str, dict[str, float | str], str]]:
    return [
        _stable_rent_scenario(),
        _growing_marketing_scenario(),
        _overbudget_software_scenario(),
        _stable_office_supplies_scenario(),
        _unusual_spike_excluded_scenario(),
    ]


def _safe_recommendation(features: dict[str, float | str], raw_prediction: float) -> float:
    clean_spend = _safe_float(features["clean_monthly_spend"])
    current_budget = _safe_float(features["current_budget"])
    avg_3 = _safe_float(features["avg_3_month_spend"])
    avg_6 = _safe_float(features["avg_6_month_spend"])
    previous = _safe_float(features["previous_month_spend"])
    prev_2 = _safe_float(features["prev_2_month_spend"])
    prev_3 = _safe_float(features["prev_3_month_spend"])
    growth_rate = _safe_float(features["growth_rate_3m"])
    budget_usage_ratio = _safe_float(features["budget_usage_ratio"])
    overspend_amount = _safe_float(features["overspend_amount"])
    months_over_budget_3 = _safe_float(features["months_over_budget_3"])
    months_over_budget_6 = _safe_float(features["months_over_budget_6"])

    recent_peak = max(clean_spend, avg_3, avg_6, previous, prev_2, prev_3)
    recent_floor = max(50.0, min(clean_spend, avg_3, avg_6, previous, prev_2, prev_3))

    lower_bound = max(50.0, recent_floor * 0.60)
    if budget_usage_ratio >= 1.05 or overspend_amount > 0 or months_over_budget_3 >= 2 or months_over_budget_6 >= 3:
        lower_bound = max(
            lower_bound,
            min(recent_peak * 1.02, current_budget + max(25.0, overspend_amount * 0.25)),
        )

    upper_multiplier = 1.35
    if budget_usage_ratio >= 1.10 or overspend_amount > 0:
        upper_multiplier = 1.50
    if growth_rate >= 0.20:
        upper_multiplier = max(upper_multiplier, min(1.65, 1.25 + growth_rate))

    upper_bound = max(
        recent_peak * upper_multiplier,
        current_budget * (1.45 if budget_usage_ratio >= 1.0 or overspend_amount > 0 else 1.25),
    )
    if current_budget <= 300.0 and recent_peak <= 250.0 and overspend_amount <= 0:
        upper_bound = min(upper_bound, max(350.0, recent_peak * 1.35))

    bounded = min(max(max(0.0, raw_prediction), lower_bound), upper_bound)
    return round(bounded, 2)


def _predict_cluster_label(artifact: dict[str, Any], features: dict[str, float | str]) -> str:
    cluster_values = [[_safe_float(features[column]) for column in CLUSTER_FEATURE_COLUMNS]]
    if "cluster_pipeline" in artifact and hasattr(artifact["cluster_pipeline"], "predict"):
        cluster_id = int(artifact["cluster_pipeline"].predict(cluster_values)[0])
    else:
        scaler = artifact.get("cluster_preprocessor")
        kmeans_model = artifact.get("kmeans_model")
        if scaler is None or kmeans_model is None:
            raise RuntimeError("Model 4 artifact is missing runtime clustering components")
        cluster_id = int(kmeans_model.predict(scaler.transform(cluster_values))[0])

    labels = artifact.get("cluster_labels") or []
    if isinstance(labels, list) and 0 <= cluster_id < len(labels):
        return str(labels[cluster_id])
    return f"behavior_cluster_{cluster_id}"


def predict_runtime_recommendation(
    artifact: dict[str, Any],
    features: dict[str, float | str],
    *,
    reason: str,
    scenario_name: str,
) -> ScenarioResult:
    missing_columns = [column for column in FEATURE_COLUMNS if column not in features]
    if missing_columns:
        raise RuntimeError(f"Runtime prediction is missing feature columns: {', '.join(missing_columns)}")

    feature_row = {column: features[column] for column in FEATURE_COLUMNS}
    raw_prediction = max(0.0, float(artifact["regressor"].predict([feature_row])[0]))
    recommended_budget = _safe_recommendation(feature_row, raw_prediction)
    current_budget = _safe_float(feature_row["current_budget"])
    change_amount = recommended_budget - current_budget
    change_percent = (change_amount / current_budget) if current_budget > 0 else 0.0

    return ScenarioResult(
        name=scenario_name,
        category_name=str(feature_row["category_name"]),
        current_budget=round(current_budget, 2),
        recommended_budget=round(recommended_budget, 2),
        expected_change_amount=round(change_amount, 2),
        expected_change_percent=round(change_percent, 4),
        cluster_label=_predict_cluster_label(artifact, feature_row),
        reason=reason,
        raw_prediction=round(raw_prediction, 2),
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


def evaluate_dataset_performance(
    artifact: dict[str, Any],
    dataset_path: Path = DEFAULT_DATASET_PATH,
) -> tuple[dict[str, float], int]:
    prepared = prepare_training_data(dataset_path)
    feature_rows = [row.features for row in prepared.rows]
    raw_predictions = [
        max(0.0, float(value))
        for value in artifact["regressor"].predict(feature_rows)
    ]
    predictions = [
        _safe_recommendation(row.features, raw_prediction)
        for row, raw_prediction in zip(prepared.rows, raw_predictions, strict=True)
    ]
    targets = [row.target for row in prepared.rows]
    return _metrics(targets, predictions), prepared.rows_used


def run_scenario_validation(artifact: dict[str, Any]) -> list[ScenarioResult]:
    return [
        predict_runtime_recommendation(
            artifact,
            features,
            reason=reason,
            scenario_name=name,
        )
        for name, features, reason in scenario_inputs()
    ]


def find_weak_behaviors(
    metrics: dict[str, float],
    scenario_results: list[ScenarioResult],
) -> list[str]:
    issues: list[str] = []
    if metrics["r2"] < 0.90:
        issues.append(f"Dataset validation R2 is lower than expected: {metrics['r2']:.4f}")
    if metrics["mape"] > 0.10:
        issues.append(f"Dataset validation MAPE is higher than preferred: {metrics['mape']:.4f}")

    scenario_by_name = {result.name: result for result in scenario_results}

    stable_rent = scenario_by_name["Scenario A: Stable Rent"]
    if stable_rent.recommended_budget > 3750.0 or stable_rent.recommended_budget < 2200.0:
        issues.append("Stable rent recommendation moves too far away from the stable spending range.")

    growing_marketing = scenario_by_name["Scenario B: Growing Marketing"]
    if growing_marketing.recommended_budget <= growing_marketing.current_budget:
        issues.append("Growing marketing recommendation did not increase above the current budget.")

    overbudget_software = scenario_by_name["Scenario C: Software Repeatedly Over Budget"]
    if overbudget_software.recommended_budget <= overbudget_software.current_budget:
        issues.append("Repeatedly over-budget software recommendation did not increase.")
    if overbudget_software.recommended_budget > 1500.0:
        issues.append("Repeatedly over-budget software recommendation increased too aggressively.")

    office_supplies = scenario_by_name["Scenario D: Office Supplies Stable Small Spend"]
    if office_supplies.recommended_budget > 400.0:
        issues.append("Stable office supplies recommendation is too high for a small steady category.")

    unusual_spike = scenario_by_name["Scenario E: Unusual Spike Excluded"]
    if unusual_spike.recommended_budget > 900.0:
        issues.append("Excluded unusual spike scenario still produces an inflated recommendation.")

    return issues


def validate_budget_recommender(
    model_path: Path = DEFAULT_MODEL_PATH,
    dataset_path: Path = DEFAULT_DATASET_PATH,
) -> ValidationResult:
    artifact = load_artifact(model_path)
    runtime_feature_fields = validate_artifact_contract(artifact)
    metrics, dataset_rows = evaluate_dataset_performance(artifact, dataset_path)
    scenario_results = run_scenario_validation(artifact)
    weak_behaviors = find_weak_behaviors(metrics, scenario_results)

    return ValidationResult(
        model_path=model_path,
        dataset_path=dataset_path,
        dataset_rows=dataset_rows,
        feature_columns=list(artifact["feature_columns"]),
        runtime_feature_fields=runtime_feature_fields,
        metrics=metrics,
        scenario_results=scenario_results,
        weak_behaviors=weak_behaviors,
        cluster_summary=list(artifact.get("cluster_summary") or []),
    )


def print_validation_report(result: ValidationResult) -> None:
    print("BizMoneyAI Model 4 Smart Budget Recommender Validation")
    print(f"Artifact: {result.model_path}")
    print(f"Dataset: {result.dataset_path}")
    print(f"Rows evaluated: {result.dataset_rows}")
    print(f"Model family: {EXPECTED_MODEL_FAMILY}")
    print(f"Feature columns confirmed: {', '.join(result.feature_columns)}")
    print("Runtime-compatible fields documented: OK")
    print("Target excluded from feature columns: OK")
    print("Metrics:")
    print(f"- MAE: {result.metrics['mae']:.4f}")
    print(f"- RMSE: {result.metrics['rmse']:.4f}")
    print(f"- R2: {result.metrics['r2']:.4f}")
    print(f"- MAPE: {result.metrics['mape']:.4f}")
    print("Cluster summary:")
    for cluster in result.cluster_summary:
        print(
            f"- {cluster['label']}: rows={cluster['row_count']} "
            f"top_category={cluster['top_category']} "
            f"top_profile={cluster['top_business_profile']} "
            f"avg_recommended_budget={cluster['avg_recommended_budget']:.2f}"
        )
    print("Scenario outputs:")
    for scenario in result.scenario_results:
        print(
            f"- {scenario.name}: category={scenario.category_name} "
            f"current_budget={scenario.current_budget:.2f} "
            f"recommended_budget={scenario.recommended_budget:.2f} "
            f"expected_change_amount={scenario.expected_change_amount:.2f} "
            f"expected_change_percent={scenario.expected_change_percent:.2%} "
            f"cluster={scenario.cluster_label} "
            f"reason={scenario.reason}"
        )
    print("Weak behavior found:")
    if result.weak_behaviors:
        for issue in result.weak_behaviors:
            print(f"- {issue}")
    else:
        print("- none")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate the BizMoneyAI Model 4 smart budget recommender.")
    parser.add_argument("--model-path", type=Path, default=DEFAULT_MODEL_PATH)
    parser.add_argument("--dataset-path", type=Path, default=DEFAULT_DATASET_PATH)
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    validation_result = validate_budget_recommender(
        model_path=args.model_path,
        dataset_path=args.dataset_path,
    )
    print_validation_report(validation_result)
