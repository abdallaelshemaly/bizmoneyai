from __future__ import annotations

import logging
import math
from calendar import monthrange
from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Literal, TypedDict

import joblib
from sqlalchemy import extract, func
from sqlalchemy.orm import Session

from app.models.ai_insight import AIInsight
from app.models.budget import Budget
from app.models.category import Category
from app.models.transaction import Transaction
from app.models.user import User
from app.services.budget_metrics import normalize_month

logger = logging.getLogger(__name__)

MODEL_PATH = Path(__file__).resolve().parents[1] / "ml" / "models" / "budget_recommender.joblib"
DEFAULT_MODEL_NAME = "BizMoneyAI Model 4 Smart Budget Recommender"
MODEL_FAMILY = "smart_budget_recommender"
UNUSUAL_TRANSACTION_RULE_ID = "ml_unusual_transaction"
UNUSUAL_TRANSACTION_SEVERITIES = ("warning", "critical")
BUDGET_RECOMMENDATION_RULE_ID = "ml_budget_recommendation"
BUDGET_RECOMMENDATION_SOURCE = "budget_recommender"
MEANINGFUL_CHANGE_PERCENT = 0.15
STRONG_CHANGE_PERCENT = 0.25
CRITICAL_CHANGE_PERCENT = 0.75

MODEL_FEATURE_COLUMNS = [
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
DEFAULT_BUSINESS_PROFILE = "small_business"
DEFAULT_COMPANY_SIZE = "small"
MIN_RECOMMENDATION = 50.0

ConfidenceLevel = Literal["low", "medium", "high", "unavailable"]


class BudgetRecommendation(TypedDict):
    category_id: int
    category_name: str
    current_budget: float
    recommended_budget: float
    confidence_level: ConfidenceLevel
    behavior_group: str
    cluster_label: str
    reason: str
    expected_change_amount: float
    expected_change_percent: float
    months_used: int


@dataclass(frozen=True)
class CategoryHistory:
    category: Category
    monthly_spend: dict[date, float]
    current_budget: float
    total_clean_expense: float
    latest_month: date

    @property
    def months_used(self) -> int:
        return sum(1 for amount in self.monthly_spend.values() if amount > 0)


def _shift_month(value: date, offset: int) -> date:
    month_index = value.year * 12 + value.month - 1 + offset
    return date(month_index // 12, month_index % 12 + 1, 1)


def _month_end(value: date) -> date:
    month_start = normalize_month(value)
    return date(month_start.year, month_start.month, monthrange(month_start.year, month_start.month)[1])


def _optional_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    if math.isnan(number) or math.isinf(number):
        return default
    return number


def _ratio(numerator: float, denominator: float) -> float:
    return numerator / denominator if denominator > 0 else 0.0


def _average(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _prediction_value(value: Any) -> float:
    return max(0.0, _safe_float(value))


def _confidence(months_used: int, *, model_ready: bool) -> ConfidenceLevel:
    if not model_ready:
        return "unavailable"
    if months_used >= 6:
        return "high"
    if months_used >= 4:
        return "medium"
    return "low"


def _fallback_confidence(months_used: int, *, model_ready: bool = True) -> ConfidenceLevel:
    if not model_ready:
        return "unavailable"
    return "low"


def _reason(
    *,
    model_ready: bool,
    months_used: int,
    current_budget: float,
    recommended_budget: float,
    clean_monthly_spend: float,
    months_over_budget_3: float = 0.0,
) -> str:
    if not model_ready:
        return "Model 4 is unavailable, so this is a conservative fallback based on clean spending history."
    if months_used < 2:
        return "Not enough clean spending history is available yet, so this is a low-confidence fallback."
    if recommended_budget > current_budget and months_over_budget_3 > 0:
        return "Clean spending shows repeated overspending, so the recommendation increases the category budget."
    if recommended_budget > current_budget and clean_monthly_spend > current_budget:
        return "Current clean spend is above budget, so the recommendation raises the category budget."
    if recommended_budget < current_budget:
        return "Clean spending is below the current budget, so the recommendation keeps the budget closer to actual use."
    return "Clean spending is stable, so the recommendation stays close to the current category budget."


def _format_money(value: float) -> str:
    return f"${value:,.2f}"


def _fallback_recommendation(
    *,
    current_budget: float,
    clean_monthly_spend: float,
    avg_3_month_spend: float,
) -> float:
    baseline = max(clean_monthly_spend, avg_3_month_spend, current_budget if current_budget > 0 else 0.0)
    if baseline <= 0:
        baseline = MIN_RECOMMENDATION
    if current_budget > 0 and clean_monthly_spend <= current_budget:
        baseline = max(clean_monthly_spend, min(current_budget, avg_3_month_spend * 1.15 if avg_3_month_spend > 0 else current_budget))
    return round(max(MIN_RECOMMENDATION, baseline), 2)


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

    recent_values = [clean_spend, avg_3, avg_6, previous, prev_2, prev_3]
    recent_peak = max(recent_values)
    positive_recent_values = [value for value in recent_values if value > 0]
    recent_floor = min(positive_recent_values) if positive_recent_values else MIN_RECOMMENDATION
    effective_budget = current_budget if current_budget > 0 else max(recent_peak, MIN_RECOMMENDATION)

    lower_bound = max(MIN_RECOMMENDATION, recent_floor * 0.60)
    if budget_usage_ratio >= 1.05 or overspend_amount > 0 or months_over_budget_3 >= 2 or months_over_budget_6 >= 3:
        lower_bound = max(
            lower_bound,
            min(recent_peak * 1.02, effective_budget + max(25.0, overspend_amount * 0.25)),
        )

    upper_multiplier = 1.35
    if budget_usage_ratio >= 1.10 or overspend_amount > 0:
        upper_multiplier = 1.50
    if growth_rate >= 0.20:
        upper_multiplier = max(upper_multiplier, min(1.65, 1.25 + growth_rate))

    upper_bound = max(
        recent_peak * upper_multiplier,
        effective_budget * (1.45 if budget_usage_ratio >= 1.0 or overspend_amount > 0 else 1.25),
        MIN_RECOMMENDATION,
    )
    if effective_budget <= 300.0 and recent_peak <= 250.0 and overspend_amount <= 0:
        upper_bound = min(upper_bound, max(350.0, recent_peak * 1.35, MIN_RECOMMENDATION))

    bounded = min(max(max(0.0, raw_prediction), lower_bound), upper_bound)
    return round(max(MIN_RECOMMENDATION, bounded), 2)


class BudgetRecommender:
    def __init__(self, model_path: Path = MODEL_PATH) -> None:
        self.model_path = model_path
        self._regressor: Any | None = None
        self._cluster_pipeline: Any | None = None
        self._cluster_preprocessor: Any | None = None
        self._kmeans_model: Any | None = None
        self._feature_columns: list[str] = []
        self._cluster_feature_columns: list[str] = []
        self._cluster_labels: list[str] = []
        self._model_name = DEFAULT_MODEL_NAME
        self._load_model()

    def _load_model(self) -> None:
        if not self.model_path.exists():
            logger.info("Budget recommender model not found at %s", self.model_path)
            return

        try:
            artifact = joblib.load(self.model_path)
        except Exception:
            logger.exception("Failed to load budget recommender model from %s", self.model_path)
            return

        if not isinstance(artifact, dict):
            logger.warning("Ignoring incompatible budget recommender artifact at %s", self.model_path)
            return

        metadata = artifact.get("metadata") if isinstance(artifact.get("metadata"), dict) else {}
        model_family = metadata.get("model_family") or artifact.get("model_family")
        regressor = artifact.get("regressor")
        feature_columns = artifact.get("feature_columns")
        cluster_feature_columns = artifact.get("cluster_feature_columns")

        if model_family != MODEL_FAMILY:
            logger.warning("Ignoring unsupported budget recommender model family: %s", model_family)
            return
        if regressor is None or not hasattr(regressor, "predict"):
            logger.warning("Ignoring budget recommender artifact without prediction support")
            return
        if feature_columns != MODEL_FEATURE_COLUMNS:
            logger.warning("Ignoring budget recommender artifact with incompatible feature columns")
            return
        if not isinstance(cluster_feature_columns, list) or not all(isinstance(column, str) for column in cluster_feature_columns):
            cluster_feature_columns = list(CLUSTER_FEATURE_COLUMNS)

        self._regressor = regressor
        self._cluster_pipeline = artifact.get("cluster_pipeline")
        self._cluster_preprocessor = artifact.get("cluster_preprocessor")
        self._kmeans_model = artifact.get("kmeans_model")
        self._feature_columns = list(feature_columns)
        self._cluster_feature_columns = list(cluster_feature_columns)
        self._cluster_labels = [str(label) for label in artifact.get("cluster_labels") or []]
        self._model_name = str(artifact.get("model_name") or metadata.get("model_name") or DEFAULT_MODEL_NAME)
        logger.info("Budget recommender loaded from %s", self.model_path)

    def is_ready(self) -> bool:
        return self._regressor is not None and self._feature_columns == MODEL_FEATURE_COLUMNS

    def _unusual_transaction_ids(self, db: Session, user_id: int) -> set[int]:
        insights = (
            db.query(AIInsight)
            .filter(
                AIInsight.user_id == user_id,
                AIInsight.rule_id == UNUSUAL_TRANSACTION_RULE_ID,
                AIInsight.severity.in_(UNUSUAL_TRANSACTION_SEVERITIES),
            )
            .all()
        )
        transaction_ids: set[int] = set()
        for insight in insights:
            transaction_id = _optional_int((insight.metadata_json or {}).get("transaction_id"))
            if transaction_id is not None:
                transaction_ids.add(transaction_id)
        return transaction_ids

    def _latest_month(self, db: Session, user_id: int) -> date:
        latest_tx_date = db.query(func.max(Transaction.date)).filter(Transaction.user_id == user_id).scalar()
        if latest_tx_date is None:
            return normalize_month(date.today())
        return normalize_month(latest_tx_date)

    def _current_budgets_by_category(
        self,
        db: Session,
        *,
        user_id: int,
        month_start: date,
    ) -> dict[int, float]:
        rows = (
            db.query(Budget.category_id, func.coalesce(func.sum(Budget.amount), 0.0))
            .filter(
                Budget.user_id == user_id,
                extract("year", Budget.month) == month_start.year,
                extract("month", Budget.month) == month_start.month,
            )
            .group_by(Budget.category_id)
            .all()
        )
        return {int(category_id): float(amount or 0.0) for category_id, amount in rows}

    def _category_histories(self, db: Session, user_id: int) -> list[CategoryHistory]:
        latest_month = self._latest_month(db, user_id)
        excluded_transaction_ids = self._unusual_transaction_ids(db, user_id)
        current_budgets = self._current_budgets_by_category(db, user_id=user_id, month_start=latest_month)

        categories = (
            db.query(Category)
            .filter(Category.user_id == user_id, Category.type != "income")
            .order_by(Category.name.asc(), Category.category_id.asc())
            .all()
        )
        category_by_id = {int(category.category_id): category for category in categories}
        spend_by_category_month: dict[int, dict[date, float]] = {
            int(category.category_id): defaultdict(float)
            for category in categories
        }
        total_by_month: dict[date, float] = defaultdict(float)

        rows = (
            db.query(Transaction)
            .filter(Transaction.user_id == user_id, Transaction.type == "expense")
            .order_by(Transaction.date.asc(), Transaction.transaction_id.asc())
            .all()
        )
        for tx in rows:
            if tx.transaction_id in excluded_transaction_ids:
                continue
            category = category_by_id.get(int(tx.category_id))
            if category is None:
                continue
            month_start = normalize_month(tx.date)
            amount = float(tx.amount or 0.0)
            spend_by_category_month[int(tx.category_id)][month_start] += amount
            total_by_month[month_start] += amount

        total_clean_expense = float(total_by_month.get(latest_month, 0.0))
        return [
            CategoryHistory(
                category=category,
                monthly_spend=dict(spend_by_category_month[int(category.category_id)]),
                current_budget=float(current_budgets.get(int(category.category_id), 0.0)),
                total_clean_expense=total_clean_expense,
                latest_month=latest_month,
            )
            for category in categories
        ]

    def _spend_for_month(self, history: CategoryHistory, month_start: date) -> float:
        return float(history.monthly_spend.get(month_start, 0.0))

    def _months_over_budget(self, history: CategoryHistory, months: int) -> float:
        if history.current_budget <= 0:
            return 0.0
        count = 0
        for offset in range(months):
            if self._spend_for_month(history, _shift_month(history.latest_month, -offset)) > history.current_budget:
                count += 1
        return float(count)

    def _build_feature_row(self, history: CategoryHistory) -> dict[str, float | str]:
        latest = history.latest_month
        clean_monthly_spend = self._spend_for_month(history, latest)
        previous_month_spend = self._spend_for_month(history, _shift_month(latest, -1))
        prev_2_month_spend = self._spend_for_month(history, _shift_month(latest, -2))
        prev_3_month_spend = self._spend_for_month(history, _shift_month(latest, -3))
        avg_3_month_spend = _average([
            clean_monthly_spend,
            previous_month_spend,
            prev_2_month_spend,
        ])
        avg_6_month_spend = _average([
            self._spend_for_month(history, _shift_month(latest, -offset))
            for offset in range(6)
        ])
        effective_budget = history.current_budget if history.current_budget > 0 else max(avg_3_month_spend, clean_monthly_spend, MIN_RECOMMENDATION)
        overspend_amount = max(clean_monthly_spend - effective_budget, 0.0)
        values: dict[str, float | str] = {
            "clean_monthly_spend": clean_monthly_spend,
            "current_budget": effective_budget,
            "previous_month_spend": previous_month_spend,
            "prev_2_month_spend": prev_2_month_spend,
            "prev_3_month_spend": prev_3_month_spend,
            "avg_3_month_spend": avg_3_month_spend,
            "avg_6_month_spend": avg_6_month_spend,
            "growth_rate_3m": _ratio(clean_monthly_spend - prev_3_month_spend, prev_3_month_spend),
            "budget_usage_ratio": _ratio(clean_monthly_spend, effective_budget),
            "overspend_amount": overspend_amount,
            "months_over_budget_3": self._months_over_budget(history, 3),
            "months_over_budget_6": self._months_over_budget(history, 6),
            "category_share_of_total": _ratio(clean_monthly_spend, history.total_clean_expense),
            "total_clean_expense": history.total_clean_expense,
            "category_name": str(history.category.name),
            "business_profile": DEFAULT_BUSINESS_PROFILE,
            "company_size": DEFAULT_COMPANY_SIZE,
        }
        return {column: values[column] for column in self._feature_columns or MODEL_FEATURE_COLUMNS}

    def _cluster_label(self, features: dict[str, float | str]) -> str:
        cluster_values = [[_safe_float(features[column]) for column in self._cluster_feature_columns or CLUSTER_FEATURE_COLUMNS]]
        try:
            if self._cluster_pipeline is not None and hasattr(self._cluster_pipeline, "predict"):
                cluster_id = int(self._cluster_pipeline.predict(cluster_values)[0])
            elif self._cluster_preprocessor is not None and self._kmeans_model is not None:
                cluster_id = int(self._kmeans_model.predict(self._cluster_preprocessor.transform(cluster_values))[0])
            else:
                return "unknown"
        except Exception:
            logger.exception("Budget recommendation cluster prediction failed")
            return "unknown"

        if 0 <= cluster_id < len(self._cluster_labels):
            return self._cluster_labels[cluster_id]
        return f"behavior_cluster_{cluster_id}"

    def _response(
        self,
        *,
        history: CategoryHistory,
        features: dict[str, float | str],
        recommended_budget: float,
        confidence_level: ConfidenceLevel,
        cluster_label: str,
        model_ready: bool,
    ) -> BudgetRecommendation:
        current_budget = round(history.current_budget, 2)
        expected_change_amount = round(recommended_budget - current_budget, 2)
        expected_change_percent = round(_ratio(expected_change_amount, current_budget), 4) if current_budget > 0 else 0.0
        reason = _reason(
            model_ready=model_ready,
            months_used=history.months_used,
            current_budget=current_budget,
            recommended_budget=recommended_budget,
            clean_monthly_spend=_safe_float(features["clean_monthly_spend"]),
            months_over_budget_3=_safe_float(features["months_over_budget_3"]),
        )
        return {
            "category_id": int(history.category.category_id),
            "category_name": str(history.category.name),
            "current_budget": current_budget,
            "recommended_budget": round(max(0.0, recommended_budget), 2),
            "confidence_level": confidence_level,
            "behavior_group": cluster_label,
            "cluster_label": cluster_label,
            "reason": reason,
            "expected_change_amount": expected_change_amount,
            "expected_change_percent": expected_change_percent,
            "months_used": history.months_used,
        }

    def _target_month(self, history: CategoryHistory) -> date:
        return _shift_month(history.latest_month, 1)

    def _budget_recommendation_scope_key(self, *, category_id: int, target_month: date) -> str:
        return f"category:{category_id}:target_month:{target_month.isoformat()}"

    def _has_budget_recommendation_insight(
        self,
        db: Session,
        *,
        user_id: int,
        target_month: date,
        scope_key: str,
    ) -> bool:
        existing = (
            db.query(AIInsight)
            .filter(
                AIInsight.user_id == user_id,
                AIInsight.rule_id == BUDGET_RECOMMENDATION_RULE_ID,
                AIInsight.period_start == target_month,
                AIInsight.period_end == _month_end(target_month),
            )
            .all()
        )
        return any((insight.metadata_json or {}).get("scope_key") == scope_key for insight in existing)

    def _should_create_budget_recommendation_insight(
        self,
        recommendation: BudgetRecommendation,
        features: dict[str, float | str],
    ) -> bool:
        if recommendation["confidence_level"] not in {"medium", "high"}:
            return False
        if recommendation["expected_change_amount"] <= 0:
            return False
        if recommendation["expected_change_percent"] < MEANINGFUL_CHANGE_PERCENT:
            return False

        repeated_overspending = _safe_float(features["months_over_budget_3"]) >= 2 or _safe_float(features["months_over_budget_6"]) >= 3
        growth_trend = _safe_float(features["growth_rate_3m"]) >= MEANINGFUL_CHANGE_PERCENT
        strong_increase = recommendation["expected_change_percent"] >= STRONG_CHANGE_PERCENT
        return repeated_overspending or growth_trend or strong_increase

    def _budget_recommendation_severity(
        self,
        recommendation: BudgetRecommendation,
        features: dict[str, float | str],
    ) -> Literal["info", "warning", "critical"]:
        months_over_budget_6 = _safe_float(features["months_over_budget_6"])
        if months_over_budget_6 >= 5 and recommendation["expected_change_percent"] >= CRITICAL_CHANGE_PERCENT:
            return "critical"
        if (
            _safe_float(features["months_over_budget_3"]) >= 2
            or recommendation["expected_change_percent"] >= STRONG_CHANGE_PERCENT
        ):
            return "warning"
        return "info"

    def _budget_recommendation_message(
        self,
        recommendation: BudgetRecommendation,
        features: dict[str, float | str],
    ) -> str:
        reasons: list[str] = []
        if _safe_float(features["growth_rate_3m"]) >= MEANINGFUL_CHANGE_PERCENT:
            reasons.append("recent growth")
        if _safe_float(features["months_over_budget_3"]) >= 2 or _safe_float(features["months_over_budget_6"]) >= 3:
            reasons.append("repeated overspending")
        reason_text = " and ".join(reasons) if reasons else "recent clean spending"
        return (
            f"Your {recommendation['category_name']} budget may be too low for next month. "
            f"Recommended budget: {_format_money(recommendation['recommended_budget'])} "
            f"based on {reason_text}."
        )

    def _maybe_create_budget_recommendation_insight(
        self,
        db: Session,
        *,
        user_id: int,
        history: CategoryHistory,
        features: dict[str, float | str],
        recommendation: BudgetRecommendation,
    ) -> bool:
        if not self._should_create_budget_recommendation_insight(recommendation, features):
            return False

        target_month = self._target_month(history)
        scope_key = self._budget_recommendation_scope_key(
            category_id=int(history.category.category_id),
            target_month=target_month,
        )
        if self._has_budget_recommendation_insight(
            db,
            user_id=user_id,
            target_month=target_month,
            scope_key=scope_key,
        ):
            return False

        insight = AIInsight(
            user_id=user_id,
            rule_id=BUDGET_RECOMMENDATION_RULE_ID,
            title=f"{recommendation['category_name']} Budget May Need Adjustment",
            message=self._budget_recommendation_message(recommendation, features),
            severity=self._budget_recommendation_severity(recommendation, features),
            period_start=target_month,
            period_end=_month_end(target_month),
            metadata_json={
                "scope_key": scope_key,
                "source": BUDGET_RECOMMENDATION_SOURCE,
                "category_id": recommendation["category_id"],
                "category_name": recommendation["category_name"],
                "current_budget": recommendation["current_budget"],
                "recommended_budget": recommendation["recommended_budget"],
                "expected_change_amount": recommendation["expected_change_amount"],
                "expected_change_percent": recommendation["expected_change_percent"],
                "confidence_level": recommendation["confidence_level"],
                "behavior_group": recommendation["behavior_group"],
                "target_month": target_month.isoformat(),
                "months_used": recommendation["months_used"],
                "months_over_budget_3": _safe_float(features["months_over_budget_3"]),
                "months_over_budget_6": _safe_float(features["months_over_budget_6"]),
                "growth_rate_3m": _safe_float(features["growth_rate_3m"]),
            },
        )
        db.add(insight)
        return True

    def _recommend_with_fallback(
        self,
        history: CategoryHistory,
        *,
        model_ready: bool,
    ) -> BudgetRecommendation:
        features = self._build_feature_row(history)
        recommended_budget = _fallback_recommendation(
            current_budget=history.current_budget,
            clean_monthly_spend=_safe_float(features["clean_monthly_spend"]),
            avg_3_month_spend=_safe_float(features["avg_3_month_spend"]),
        )
        return self._response(
            history=history,
            features=features,
            recommended_budget=recommended_budget,
            confidence_level=_fallback_confidence(history.months_used, model_ready=model_ready),
            cluster_label="fallback",
            model_ready=model_ready,
        )

    def recommend_budgets_for_user(self, db: Session, user: User) -> list[BudgetRecommendation]:
        user_id = int(user.user_id)
        histories = self._category_histories(db, int(user.user_id))
        model_ready = self.is_ready()
        recommendations: list[BudgetRecommendation] = []
        insight_created = False

        for history in histories:
            try:
                if not model_ready or history.months_used < 2:
                    recommendations.append(self._recommend_with_fallback(history, model_ready=model_ready))
                    continue

                features = self._build_feature_row(history)
                assert self._regressor is not None
                raw_prediction = _prediction_value(self._regressor.predict([features])[0])
                recommended_budget = _safe_recommendation(features, raw_prediction)
                cluster_label = self._cluster_label(features)
                recommendation = self._response(
                    history=history,
                    features=features,
                    recommended_budget=recommended_budget,
                    confidence_level=_confidence(history.months_used, model_ready=True),
                    cluster_label=cluster_label,
                    model_ready=True,
                )
                recommendations.append(recommendation)
                insight_created = (
                    self._maybe_create_budget_recommendation_insight(
                        db,
                        user_id=user_id,
                        history=history,
                        features=features,
                        recommendation=recommendation,
                    )
                    or insight_created
                )
            except Exception:
                logger.exception("Budget recommendation failed for category %s", history.category.category_id)
                recommendations.append(self._recommend_with_fallback(history, model_ready=False))

        if insight_created:
            try:
                db.commit()
            except Exception:
                db.rollback()
                logger.exception("Failed to create budget recommendation insights for user %s", user_id)

        return recommendations


recommender = BudgetRecommender()


def is_ready() -> bool:
    return recommender.is_ready()


def recommend_budgets_for_user(db: Session, user: User) -> list[BudgetRecommendation]:
    return recommender.recommend_budgets_for_user(db, user)
