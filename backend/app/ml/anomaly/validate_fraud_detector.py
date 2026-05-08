from __future__ import annotations

import argparse
import csv
from pathlib import Path
from typing import Any

import joblib
import numpy as np
from sklearn.metrics import confusion_matrix, f1_score, precision_score, recall_score

from app.services.fraud_detector import (
    CRITICAL_THRESHOLD,
    FEATURE_COLUMNS,
    MODEL_FAMILY,
    WARNING_THRESHOLD,
    FraudDetector,
    build_feature_row,
    build_feature_values,
)


DEFAULT_DATASET_PATH = (
    Path(__file__).resolve().parents[3]
    / "data"
    / "processed"
    / "bizmoneyai_unusual_transactions.csv"
)
DEFAULT_MODEL_PATH = Path(__file__).resolve().parents[1] / "models" / "fraud_detector.joblib"
TARGET_COLUMN = "is_outlier"


def _load_artifact(model_path: Path) -> dict[str, Any]:
    if not model_path.exists():
        raise FileNotFoundError(f"Model artifact not found: {model_path}")
    artifact = joblib.load(model_path)
    if not isinstance(artifact, dict):
        raise TypeError("Model artifact is not a dictionary")
    return artifact


def inspect_artifact(model_path: Path) -> dict[str, Any]:
    artifact = _load_artifact(model_path)
    model = artifact.get("model")
    metadata = artifact.get("metadata") if isinstance(artifact.get("metadata"), dict) else {}
    thresholds = artifact.get("risk_thresholds") or metadata.get("risk_thresholds")

    print("Artifact inspection:")
    print(f"- path: {model_path}")
    print(f"- contains model: {model is not None}")
    print(f"- model type: {type(model).__name__ if model is not None else 'missing'}")
    print(f"- has decision_function: {hasattr(model, 'decision_function')}")
    print(f"- feature columns match runtime: {artifact.get('feature_columns') == FEATURE_COLUMNS}")
    print(f"- model family: {metadata.get('model_family') or artifact.get('model_family')}")
    print(f"- expected model family: {MODEL_FAMILY}")
    print(f"- risk thresholds: {thresholds}")
    print(f"- trained at: {metadata.get('trained_at')}")
    print(f"- saved metrics: {metadata.get('metrics')}")
    return artifact


def _runtime_examples() -> list[tuple[str, dict[str, object]]]:
    return [
        (
            "normal office supplies",
            {
                "category_name": "Office Supplies",
                "amount": 120.0,
                "type": "expense",
                "description": "Office purchase",
                "date": "2026-04-10",
                "budget_amount": 1500.0,
                "budget_spent_before": 420.0,
                "user_avg_amount": 600.0,
                "category_avg_amount": 240.0,
                "recent_transaction_count": 12,
            },
        ),
        (
            "normal services income",
            {
                "category_name": "Services Revenue",
                "amount": 6800.0,
                "type": "income",
                "description": "Monthly services revenue",
                "date": "2026-04-15",
                "user_avg_amount": 6500.0,
                "category_avg_amount": 6500.0,
                "recent_transaction_count": 6,
            },
        ),
        (
            "warning budget overspend",
            {
                "category_name": "Software",
                "amount": 8500.0,
                "type": "expense",
                "description": "Urgent software vendor renewal",
                "date": "2026-04-20",
                "budget_amount": 4500.0,
                "budget_spent_before": 3900.0,
                "user_avg_amount": 900.0,
                "category_avg_amount": 850.0,
                "recent_transaction_count": 2,
            },
        ),
        (
            "critical marketing transfer",
            {
                "category_name": "Marketing",
                "amount": 45000.0,
                "type": "expense",
                "description": "Emergency vendor transfer for urgent campaign settlement",
                "date": "2026-04-25",
                "budget_amount": 4000.0,
                "budget_spent_before": 3999.0,
                "user_avg_amount": 1200.0,
                "category_avg_amount": 1100.0,
                "recent_transaction_count": 1,
            },
        ),
    ]


def _risk_score_from_raw(raw_score: float, thresholds: dict[str, float]) -> float:
    warning = float(thresholds.get("warning_raw", 0.0))
    critical = float(thresholds.get("critical_raw", warning + 0.08))
    floor = float(thresholds.get("raw_score_floor", warning - 0.20))
    if critical <= warning:
        critical = warning + 0.08
    if floor >= warning:
        floor = warning - 0.20

    if raw_score < warning:
        return max(0.0, min(0.49, 0.49 * ((raw_score - floor) / max(warning - floor, 1e-6))))
    if raw_score < critical:
        return max(0.50, min(0.79, 0.50 + 0.29 * ((raw_score - warning) / max(critical - warning, 1e-6))))
    return max(0.80, min(1.0, 0.80 + 0.20 * ((raw_score - critical) / max(critical - warning, 1e-6))))


def _contextual_risk_floor(row: dict[str, str]) -> float:
    features = build_feature_values(row)
    amount = float(row.get("amount") or 0.0)
    is_expense = features["is_expense"] >= 0.5
    if is_expense and (features["budget_overspend_ratio"] >= 4.0 or (features["amount_to_budget_ratio"] >= 8.0 and amount >= 10_000)):
        return 0.92
    if is_expense and (features["budget_overspend_ratio"] >= 1.0 or features["projected_budget_usage_ratio"] >= 2.0):
        return 0.70
    if is_expense and amount >= 10_000 and features["amount_to_user_avg_ratio"] >= 10.0 and features["amount_to_category_avg_ratio"] >= 8.0:
        return 0.86
    if is_expense and amount >= 5_000 and features["amount_to_user_avg_ratio"] >= 4.0 and features["amount_to_category_avg_ratio"] >= 3.5:
        return 0.62
    if is_expense and amount >= 15_000 and features["description_urgency_score"] >= 0.45:
        return 0.70
    if is_expense and amount >= 25_000:
        return 0.60
    if not is_expense and amount >= 50_000 and features["amount_to_user_avg_ratio"] >= 8.0:
        return 0.62
    return 0.0


def run_runtime_examples(model_path: Path) -> None:
    detector = FraudDetector(model_path=model_path)
    print("Runtime prediction examples:")
    print(f"- detector ready: {detector.is_ready()}")
    for label, payload in _runtime_examples():
        result = detector.predict(payload)
        print(
            f"- {label}: score={result['fraud_probability']:.6f}, "
            f"risk_level={result['risk_level']}, is_unusual={result['is_unusual']}"
        )


def evaluate_dataset(model_path: Path, dataset_path: Path) -> None:
    if not dataset_path.exists():
        print(f"Dataset evaluation skipped; dataset not found at {dataset_path}")
        return

    detector = FraudDetector(model_path=model_path)
    artifact = _load_artifact(model_path)
    model = artifact.get("model")
    metadata = artifact.get("metadata") if isinstance(artifact.get("metadata"), dict) else {}
    thresholds = artifact.get("risk_thresholds") or metadata.get("risk_thresholds") or {}
    if not detector.is_ready() or model is None or not hasattr(model, "decision_function"):
        print("Dataset evaluation skipped; detector is not ready")
        return

    rows: list[dict[str, str]] = []
    y_true: list[int] = []
    with dataset_path.open("r", newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            rows.append(row)
            y_true.append(int(float(row.get(TARGET_COLUMN) or 0)))

    x = np.vstack([build_feature_row(row)[0] for row in rows]).astype(np.float32)
    raw_scores = -model.decision_function(x)
    risk_scores = np.array(
        [
            max(_risk_score_from_raw(float(raw), thresholds), _contextual_risk_floor(row))
            for row, raw in zip(rows, raw_scores, strict=True)
        ],
        dtype=np.float32,
    )
    y_pred = [1 if score >= WARNING_THRESHOLD else 0 for score in risk_scores]
    warning_count = int(((risk_scores >= WARNING_THRESHOLD) & (risk_scores < CRITICAL_THRESHOLD)).sum())
    critical_count = int((risk_scores >= CRITICAL_THRESHOLD).sum())

    y_true_array = np.array(y_true, dtype=np.int8)
    y_pred_array = np.array(y_pred, dtype=np.int8)
    matrix = confusion_matrix(y_true_array, y_pred_array, labels=[0, 1])
    print("Dataset validation:")
    print(f"- precision: {precision_score(y_true_array, y_pred_array, zero_division=0):.6f}")
    print(f"- recall: {recall_score(y_true_array, y_pred_array, zero_division=0):.6f}")
    print(f"- f1-score: {f1_score(y_true_array, y_pred_array, zero_division=0):.6f}")
    print(f"- confusion matrix [[tn, fp], [fn, tp]]: {matrix.tolist()}")
    print(f"- warning predictions: {warning_count}")
    print(f"- critical predictions: {critical_count}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate the BizMoneyAI Model 2 unusual transaction detector.")
    parser.add_argument("--dataset-path", type=Path, default=DEFAULT_DATASET_PATH)
    parser.add_argument("--model-path", type=Path, default=DEFAULT_MODEL_PATH)
    parser.add_argument("--dataset-eval", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    inspect_artifact(args.model_path)
    run_runtime_examples(args.model_path)
    if args.dataset_eval:
        evaluate_dataset(args.model_path, args.dataset_path)


if __name__ == "__main__":
    main()
