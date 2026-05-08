from __future__ import annotations

import logging
import math
from datetime import date, datetime
from pathlib import Path
from typing import Any, Literal, TypedDict

import joblib
import numpy as np

logger = logging.getLogger(__name__)

MODEL_PATH = Path(__file__).resolve().parents[1] / "ml" / "models" / "fraud_detector.joblib"
DEFAULT_MODEL_NAME = "BizMoneyAI Model 2 Fraud Detector"
MODEL_FAMILY = "bizmoneyai_unusual_transaction"
WARNING_THRESHOLD = 0.50
CRITICAL_THRESHOLD = 0.80
DEFAULT_WARNING_RAW_THRESHOLD = 0.0
DEFAULT_CRITICAL_RAW_THRESHOLD = 0.08

FEATURE_COLUMNS = [
    "log_amount",
    "is_expense",
    "is_income",
    "month",
    "day_of_month",
    "day_of_week",
    "has_budget",
    "budget_amount_log",
    "budget_usage_ratio",
    "amount_to_budget_ratio",
    "projected_budget_usage_ratio",
    "budget_overspend_ratio",
    "amount_to_user_avg_ratio",
    "amount_to_category_avg_ratio",
    "recent_transaction_count_30d",
    "description_urgency_score",
    "category_risk_weight",
]

RiskLevel = Literal["normal", "warning", "critical"]


class FraudPrediction(TypedDict):
    is_unusual: bool
    fraud_probability: float
    risk_level: RiskLevel
    model_name: str


def _clamp(value: float, lower: float = 0.0, upper: float = 1.0) -> float:
    return max(lower, min(upper, value))


def _safe_float(payload: dict[str, Any], key: str, default: float = 0.0) -> float:
    value = payload.get(key, default)
    if value in (None, ""):
        return default
    try:
        if isinstance(value, str):
            value = value.replace(",", "")
        number = float(value)
    except (TypeError, ValueError):
        return default
    if math.isnan(number) or math.isinf(number):
        return default
    return number


def _positive_context_value(payload: dict[str, Any], keys: tuple[str, ...], default: float) -> float:
    for key in keys:
        value = _safe_float(payload, key, default=0.0)
        if value > 0:
            return value
    return default


def _transaction_type(payload: dict[str, Any]) -> str:
    raw_value = payload.get("type") or payload.get("transaction_type") or ""
    normalized = str(raw_value).strip().lower().replace("-", "_").replace(" ", "_")
    if normalized in {"income", "cash_in", "credit", "revenue"}:
        return "income"
    return "expense"


def _payload_date(payload: dict[str, Any]) -> date:
    raw_value = payload.get("date") or payload.get("transaction_date")
    if isinstance(raw_value, datetime):
        return raw_value.date()
    if isinstance(raw_value, date):
        return raw_value
    if isinstance(raw_value, str) and raw_value.strip():
        value = raw_value.strip()
        if len(value) == 7 and value[4] == "-":
            value = f"{value}-01"
        try:
            return date.fromisoformat(value)
        except ValueError:
            logger.debug("Ignoring invalid transaction date for fraud detection: %s", raw_value)
    return date.today()


def _description_urgency_score(payload: dict[str, Any]) -> float:
    text = str(payload.get("description") or "").lower()
    if not text:
        return 0.0

    weighted_terms = {
        "urgent": 0.25,
        "emergency": 0.30,
        "immediate": 0.25,
        "rush": 0.20,
        "wire": 0.25,
        "transfer": 0.20,
        "settlement": 0.15,
        "offshore": 0.30,
        "manual": 0.15,
        "override": 0.20,
        "cash": 0.15,
        "campaign": 0.10,
        "vendor": 0.10,
    }
    return _clamp(sum(weight for term, weight in weighted_terms.items() if term in text))


def _category_risk_weight(payload: dict[str, Any]) -> float:
    category = str(payload.get("category_name") or payload.get("category") or "").lower()
    if not category:
        return 0.35

    weights = {
        "marketing": 0.60,
        "advertising": 0.58,
        "vendor": 0.58,
        "consulting": 0.55,
        "contractor": 0.55,
        "travel": 0.48,
        "software": 0.45,
        "operations": 0.42,
        "payroll": 0.35,
        "rent": 0.30,
        "utilities": 0.25,
        "office": 0.25,
        "sales": 0.20,
        "revenue": 0.18,
    }
    for keyword, weight in weights.items():
        if keyword in category:
            return weight
    return 0.35


def build_feature_values(payload: dict[str, Any]) -> dict[str, float]:
    amount = max(0.0, _safe_float(payload, "amount"))
    transaction_type = _transaction_type(payload)
    tx_date = _payload_date(payload)

    budget_amount = max(0.0, _safe_float(payload, "budget_amount"))
    budget_spent_before = max(0.0, _safe_float(payload, "budget_spent_before"))
    if budget_amount > 0:
        budget_usage_ratio = _safe_float(
            payload,
            "budget_usage_ratio",
            budget_spent_before / budget_amount,
        )
        amount_to_budget_ratio = amount / budget_amount
        projected_budget_usage_ratio = (budget_spent_before + amount) / budget_amount
    else:
        budget_usage_ratio = 0.0
        amount_to_budget_ratio = 0.0
        projected_budget_usage_ratio = 0.0

    default_avg = 5_000.0 if transaction_type == "income" else 750.0
    user_avg_amount = _positive_context_value(
        payload,
        ("user_avg_amount", "user_average_amount", "average_amount"),
        default_avg,
    )
    category_avg_amount = _positive_context_value(
        payload,
        ("category_avg_amount", "category_average_amount"),
        user_avg_amount,
    )

    return {
        "log_amount": math.log1p(amount),
        "is_expense": 1.0 if transaction_type == "expense" else 0.0,
        "is_income": 1.0 if transaction_type == "income" else 0.0,
        "month": float(tx_date.month),
        "day_of_month": float(tx_date.day),
        "day_of_week": float(tx_date.weekday()),
        "has_budget": 1.0 if budget_amount > 0 else 0.0,
        "budget_amount_log": math.log1p(budget_amount),
        "budget_usage_ratio": max(0.0, budget_usage_ratio),
        "amount_to_budget_ratio": max(0.0, amount_to_budget_ratio),
        "projected_budget_usage_ratio": max(0.0, projected_budget_usage_ratio),
        "budget_overspend_ratio": max(0.0, projected_budget_usage_ratio - 1.0),
        "amount_to_user_avg_ratio": amount / user_avg_amount,
        "amount_to_category_avg_ratio": amount / category_avg_amount,
        "recent_transaction_count_30d": max(0.0, _safe_float(payload, "recent_transaction_count")),
        "description_urgency_score": _description_urgency_score(payload),
        "category_risk_weight": _category_risk_weight(payload),
    }


def build_feature_row(payload: dict[str, Any], feature_columns: list[str] | None = None) -> np.ndarray:
    features = build_feature_values(payload)
    columns = feature_columns or FEATURE_COLUMNS
    return np.array([[features.get(column, 0.0) for column in columns]], dtype=np.float32)


class FraudDetector:
    def __init__(self, model_path: Path = MODEL_PATH) -> None:
        self.model_path = model_path
        self._model: Any | None = None
        self._feature_columns: list[str] = []
        self._model_name = DEFAULT_MODEL_NAME
        self._raw_warning_threshold = DEFAULT_WARNING_RAW_THRESHOLD
        self._raw_critical_threshold = DEFAULT_CRITICAL_RAW_THRESHOLD
        self._raw_score_floor = -0.20
        self._load_model()

    def _load_model(self) -> None:
        if not self.model_path.exists():
            logger.info("Fraud detector model not found at %s", self.model_path)
            return

        try:
            artifact = joblib.load(self.model_path)
        except Exception:
            logger.exception("Failed to load fraud detector model from %s", self.model_path)
            return

        if not isinstance(artifact, dict):
            logger.warning("Ignoring incompatible fraud detector artifact at %s", self.model_path)
            return

        model = artifact.get("model")
        feature_columns = artifact.get("feature_columns")
        metadata = artifact.get("metadata") if isinstance(artifact.get("metadata"), dict) else {}
        model_family = metadata.get("model_family") or artifact.get("model_family")

        if model_family not in {None, MODEL_FAMILY}:
            logger.warning("Ignoring unsupported fraud detector model family: %s", model_family)
            return

        if model is None or not (hasattr(model, "decision_function") or hasattr(model, "score_samples")):
            logger.warning("Ignoring fraud detector artifact without anomaly scoring support")
            return

        if feature_columns != FEATURE_COLUMNS:
            logger.warning("Ignoring fraud detector artifact with incompatible feature columns")
            return

        thresholds = artifact.get("risk_thresholds") or metadata.get("risk_thresholds") or {}
        try:
            raw_warning_threshold = float(thresholds.get("warning_raw", DEFAULT_WARNING_RAW_THRESHOLD))
            raw_critical_threshold = float(thresholds.get("critical_raw", DEFAULT_CRITICAL_RAW_THRESHOLD))
            raw_score_floor = float(thresholds.get("raw_score_floor", raw_warning_threshold - 0.20))
        except (TypeError, ValueError):
            raw_warning_threshold = DEFAULT_WARNING_RAW_THRESHOLD
            raw_critical_threshold = DEFAULT_CRITICAL_RAW_THRESHOLD
            raw_score_floor = raw_warning_threshold - 0.20

        if raw_critical_threshold <= raw_warning_threshold:
            raw_critical_threshold = raw_warning_threshold + 0.08
        if raw_score_floor >= raw_warning_threshold:
            raw_score_floor = raw_warning_threshold - 0.20

        self._model = model
        self._feature_columns = feature_columns
        self._raw_warning_threshold = raw_warning_threshold
        self._raw_critical_threshold = raw_critical_threshold
        self._raw_score_floor = raw_score_floor
        self._model_name = str(metadata.get("model_name") or DEFAULT_MODEL_NAME)
        logger.info("Fraud detector loaded from %s", self.model_path)

    def is_ready(self) -> bool:
        return self._model is not None and self._feature_columns == FEATURE_COLUMNS

    def _normal_response(self) -> FraudPrediction:
        return {
            "is_unusual": False,
            "fraud_probability": 0.0,
            "risk_level": "normal",
            "model_name": self._model_name,
        }

    def _raw_anomaly_score(self, feature_row: np.ndarray) -> float:
        if self._model is None:
            return self._raw_score_floor

        if hasattr(self._model, "decision_function"):
            return -float(self._model.decision_function(feature_row)[0])
        return -float(self._model.score_samples(feature_row)[0])

    def _model_risk_score(self, raw_score: float) -> float:
        warning = self._raw_warning_threshold
        critical = self._raw_critical_threshold
        floor = self._raw_score_floor

        if raw_score < warning:
            return _clamp(0.49 * ((raw_score - floor) / max(warning - floor, 1e-6)), 0.0, 0.49)
        if raw_score < critical:
            return _clamp(0.50 + 0.29 * ((raw_score - warning) / max(critical - warning, 1e-6)), 0.50, 0.79)
        return _clamp(0.80 + 0.20 * ((raw_score - critical) / max(critical - warning, 1e-6)), 0.80, 1.0)

    def _contextual_risk_floor(self, features: dict[str, float]) -> float:
        amount_to_budget = features["amount_to_budget_ratio"]
        projected_budget = features["projected_budget_usage_ratio"]
        overspend = features["budget_overspend_ratio"]
        user_ratio = features["amount_to_user_avg_ratio"]
        category_ratio = features["amount_to_category_avg_ratio"]
        urgency = features["description_urgency_score"]
        log_amount = features["log_amount"]
        amount = math.expm1(log_amount)
        is_expense = features["is_expense"] >= 0.5

        if is_expense and (overspend >= 4.0 or (amount_to_budget >= 8.0 and amount >= 10_000)):
            return 0.92
        if is_expense and (overspend >= 1.0 or projected_budget >= 2.0):
            return 0.70
        if is_expense and amount >= 10_000 and user_ratio >= 10.0 and category_ratio >= 8.0:
            return 0.86
        if is_expense and amount >= 5_000 and user_ratio >= 4.0 and category_ratio >= 3.5:
            return 0.62
        if is_expense and amount >= 15_000 and urgency >= 0.45:
            return 0.70
        if is_expense and amount >= 25_000:
            return 0.60
        if not is_expense and amount >= 50_000 and user_ratio >= 8.0:
            return 0.62
        return 0.0

    def _risk_level(self, risk_score: float) -> RiskLevel:
        if risk_score >= CRITICAL_THRESHOLD:
            return "critical"
        if risk_score >= WARNING_THRESHOLD:
            return "warning"
        return "normal"

    def predict(self, payload: dict[str, Any]) -> FraudPrediction:
        if not self.is_ready():
            return self._normal_response()

        try:
            feature_row = build_feature_row(payload, self._feature_columns)
            raw_score = self._raw_anomaly_score(feature_row)
            features = build_feature_values(payload)
            risk_score = max(self._model_risk_score(raw_score), self._contextual_risk_floor(features))
            risk_score = _clamp(risk_score)
            risk_level = self._risk_level(risk_score)
            return {
                "is_unusual": risk_level != "normal",
                "fraud_probability": round(risk_score, 6),
                "risk_level": risk_level,
                "model_name": self._model_name,
            }
        except Exception:
            logger.exception("Fraud detector prediction failed")
            return self._normal_response()


detector = FraudDetector()


def is_ready() -> bool:
    return detector.is_ready()


def predict(payload: dict[str, Any]) -> FraudPrediction:
    return detector.predict(payload)
