from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import sklearn
from sklearn.ensemble import IsolationForest
from sklearn.metrics import confusion_matrix, f1_score, precision_score, recall_score
from sklearn.model_selection import train_test_split

from app.services.fraud_detector import (
    CRITICAL_THRESHOLD,
    FEATURE_COLUMNS,
    MODEL_FAMILY,
    WARNING_THRESHOLD,
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
RANDOM_STATE = 42
TEST_SIZE = 0.2


def _load_dataset(dataset_path: Path) -> tuple[list[dict[str, str]], np.ndarray, np.ndarray]:
    if not dataset_path.exists():
        raise FileNotFoundError(
            f"BizMoneyAI unusual transaction dataset not found at {dataset_path}. "
            "Run app.ml.anomaly.generate_bizmoneyai_fraud_data first."
        )

    rows: list[dict[str, str]] = []
    labels: list[int] = []
    features: list[np.ndarray] = []
    with dataset_path.open("r", newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        if not reader.fieldnames or TARGET_COLUMN not in reader.fieldnames:
            raise ValueError(f"Dataset must include {TARGET_COLUMN!r}")
        for row in reader:
            rows.append(row)
            labels.append(int(float(row[TARGET_COLUMN] or 0)))
            features.append(build_feature_row(row)[0])

    if not rows:
        raise ValueError(f"Dataset is empty: {dataset_path}")

    return rows, np.vstack(features).astype(np.float32), np.array(labels, dtype=np.int8)


def _risk_score_from_raw(raw_score: float, thresholds: dict[str, float]) -> float:
    warning = thresholds["warning_raw"]
    critical = thresholds["critical_raw"]
    floor = thresholds["raw_score_floor"]

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


def _classify(score: float) -> int:
    return 1 if score >= WARNING_THRESHOLD else 0


def _target_distribution(y: np.ndarray) -> dict[str, int]:
    values, counts = np.unique(y, return_counts=True)
    return {str(int(value)): int(count) for value, count in zip(values, counts)}


def _calibrate_thresholds(model: IsolationForest, normal_x: np.ndarray, outlier_x: np.ndarray) -> dict[str, float]:
    normal_raw = -model.decision_function(normal_x)
    outlier_raw = -model.decision_function(outlier_x) if len(outlier_x) else np.array([0.08], dtype=np.float32)

    warning_raw = max(0.0, float(np.quantile(normal_raw, 0.99)))
    critical_raw = max(warning_raw + 0.03, float(np.quantile(outlier_raw, 0.58)))
    raw_score_floor = min(float(np.quantile(normal_raw, 0.01)), warning_raw - 0.20)
    return {
        "warning_raw": warning_raw,
        "critical_raw": critical_raw,
        "raw_score_floor": raw_score_floor,
    }


def _evaluate(
    model: IsolationForest,
    rows: list[dict[str, str]],
    x: np.ndarray,
    y: np.ndarray,
    thresholds: dict[str, float],
) -> dict[str, Any]:
    raw_scores = -model.decision_function(x)
    risk_scores = np.array(
        [
            max(_risk_score_from_raw(float(raw), thresholds), _contextual_risk_floor(row))
            for row, raw in zip(rows, raw_scores, strict=True)
        ],
        dtype=np.float32,
    )
    predictions = np.array([_classify(float(score)) for score in risk_scores], dtype=np.int8)
    matrix = confusion_matrix(y, predictions, labels=[0, 1])
    return {
        "precision": float(precision_score(y, predictions, zero_division=0)),
        "recall": float(recall_score(y, predictions, zero_division=0)),
        "f1_score": float(f1_score(y, predictions, zero_division=0)),
        "confusion_matrix": matrix.tolist(),
        "normal_risk_p95": float(np.quantile(risk_scores[y == 0], 0.95)) if np.any(y == 0) else None,
        "outlier_risk_p05": float(np.quantile(risk_scores[y == 1], 0.05)) if np.any(y == 1) else None,
        "warning_count": int(((risk_scores >= WARNING_THRESHOLD) & (risk_scores < CRITICAL_THRESHOLD)).sum()),
        "critical_count": int((risk_scores >= CRITICAL_THRESHOLD).sum()),
    }


def train(dataset_path: Path, model_path: Path) -> dict[str, Any]:
    rows, x, y = _load_dataset(dataset_path)
    indices = np.arange(y.shape[0])
    train_indices, test_indices = train_test_split(
        indices,
        test_size=TEST_SIZE,
        random_state=RANDOM_STATE,
        stratify=y,
    )
    normal_train_indices = train_indices[y[train_indices] == 0]

    print(f"Loading BizMoneyAI unusual transaction dataset from {dataset_path}")
    print(f"Dataset shape: {x.shape[0]} rows, {x.shape[1]} features")
    print(f"Feature columns: {', '.join(FEATURE_COLUMNS)}")
    print(f"Target distribution: {_target_distribution(y)}")
    print(f"Training IsolationForest on {len(normal_train_indices)} normal rows")

    model = IsolationForest(
        n_estimators=300,
        contamination=0.04,
        max_samples="auto",
        random_state=RANDOM_STATE,
        n_jobs=-1,
    )
    model.fit(x[normal_train_indices])

    thresholds = _calibrate_thresholds(model, x[normal_train_indices], x[y == 1])
    train_metrics = _evaluate(
        model,
        [rows[index] for index in train_indices],
        x[train_indices],
        y[train_indices],
        thresholds,
    )
    test_metrics = _evaluate(
        model,
        [rows[index] for index in test_indices],
        x[test_indices],
        y[test_indices],
        thresholds,
    )

    print("Risk thresholds:")
    print(f"- warning raw score: {thresholds['warning_raw']:.6f}")
    print(f"- critical raw score: {thresholds['critical_raw']:.6f}")
    print("Holdout metrics:")
    print(f"- precision: {test_metrics['precision']:.6f}")
    print(f"- recall: {test_metrics['recall']:.6f}")
    print(f"- f1-score: {test_metrics['f1_score']:.6f}")
    print(f"- confusion matrix [[tn, fp], [fn, tp]]: {test_metrics['confusion_matrix']}")

    metadata = {
        "model_name": "BizMoneyAI Model 2 Fraud Detector",
        "model_family": MODEL_FAMILY,
        "model_type": "IsolationForest",
        "trained_at": datetime.now(timezone.utc).isoformat(),
        "dataset_path": str(dataset_path),
        "target_column": TARGET_COLUMN,
        "feature_columns": FEATURE_COLUMNS,
        "risk_thresholds": thresholds,
        "warning_threshold": WARNING_THRESHOLD,
        "critical_threshold": CRITICAL_THRESHOLD,
        "random_state": RANDOM_STATE,
        "test_size": TEST_SIZE,
        "sklearn_version": sklearn.__version__,
        "parameters": {
            "n_estimators": 300,
            "contamination": 0.04,
            "max_samples": "auto",
            "random_state": RANDOM_STATE,
            "n_jobs": -1,
        },
        "train_rows": int(len(train_indices)),
        "test_rows": int(len(test_indices)),
        "target_distribution": {
            "all": _target_distribution(y),
            "train": _target_distribution(y[train_indices]),
            "test": _target_distribution(y[test_indices]),
        },
        "metrics": {
            "train": train_metrics,
            "test": test_metrics,
        },
        "notes": [
            "IsolationForest is trained on normal BizMoneyAI-style transactions.",
            "Synthetic outlier labels are used only for threshold calibration and validation.",
            "Runtime prediction uses amount, type, category, description, date, budget context, and user/category history.",
        ],
    }

    artifact = {
        "model": model,
        "feature_columns": FEATURE_COLUMNS,
        "model_family": MODEL_FAMILY,
        "risk_thresholds": thresholds,
        "metadata": metadata,
    }
    model_path.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(artifact, model_path)
    print(f"Saved fraud detector artifact to {model_path}")
    return artifact


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Train the BizMoneyAI unusual transaction IsolationForest model.")
    parser.add_argument("--dataset-path", type=Path, default=DEFAULT_DATASET_PATH)
    parser.add_argument("--model-path", type=Path, default=DEFAULT_MODEL_PATH)
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    train(args.dataset_path, args.model_path)
