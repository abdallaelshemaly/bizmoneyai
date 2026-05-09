from __future__ import annotations

import logging
from calendar import monthrange
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any, Literal, TypedDict

import joblib
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.ai_insight import AIInsight
from app.models.budget import Budget
from app.models.category import Category
from app.models.transaction import Transaction
from app.services.budget_metrics import normalize_month

logger = logging.getLogger(__name__)

MODEL_PATH = Path(__file__).resolve().parents[1] / "ml" / "models" / "spending_forecaster.joblib"
DEFAULT_MODEL_NAME = "BizMoneyAI Model 3 Spending Forecaster"
MODEL_FAMILY = "bizmoneyai_spending_forecast"
UNUSUAL_TRANSACTION_RULE_ID = "ml_unusual_transaction"
UNUSUAL_TRANSACTION_SEVERITIES = ("warning", "critical")
FORECAST_RISK_RULE_ID = "ml_spending_forecast_risk"
FORECAST_RISK_SOURCE = "spending_forecaster"
MEANINGFUL_OVER_BUDGET_FLOOR = 100.0
MEANINGFUL_OVER_BUDGET_RATIO = 0.10
CRITICAL_BUDGET_RATIO = 1.50

ConfidenceLevel = Literal["low", "medium", "high", "unavailable"]


class SpendingForecast(TypedDict):
    predicted_next_month_expense: float | None
    confidence_level: ConfidenceLevel
    model_name: str
    months_used: int
    current_month_expense: float
    previous_month_expense: float
    rolling_3_month_expense_avg: float
    budget_total: float
    forecast_vs_budget: float | None
    top_reduction_categories: list[str]
    recommendation: str


@dataclass
class MonthSnapshot:
    month_start: date
    total_income: float = 0.0
    clean_total_expense: float = 0.0
    transaction_count: int = 0
    expense_transaction_count: int = 0
    income_transaction_count: int = 0
    category_ids: set[int] = field(default_factory=set)
    expense_by_category: dict[str, float] = field(default_factory=lambda: defaultdict(float))
    budget_total: float = 0.0

    @property
    def category_count(self) -> int:
        return len(self.category_ids)

    @property
    def budget_usage_ratio(self) -> float:
        if self.budget_total <= 0:
            return 0.0
        return self.clean_total_expense / self.budget_total

    @property
    def budget_exceeded(self) -> float:
        return 1.0 if self.budget_total > 0 and self.clean_total_expense > self.budget_total else 0.0

    @property
    def expense_to_income_ratio(self) -> float:
        if self.total_income <= 0:
            return 0.0
        return self.clean_total_expense / self.total_income

    @property
    def top_expense_categories(self) -> list[str]:
        return [
            category
            for category, _amount in sorted(
                self.expense_by_category.items(),
                key=lambda item: (-item[1], item[0].lower()),
            )
        ]


def _month_delta(start: date, end: date) -> int:
    return (end.year - start.year) * 12 + (end.month - start.month)


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


def _safe_prediction_value(value: Any) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, number)


def _optional_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _unavailable_response(
    *,
    model_name: str = DEFAULT_MODEL_NAME,
    months_used: int = 0,
    current_month_expense: float = 0.0,
    previous_month_expense: float = 0.0,
    rolling_3_month_expense_avg: float = 0.0,
    budget_total: float = 0.0,
) -> SpendingForecast:
    return {
        "predicted_next_month_expense": None,
        "confidence_level": "unavailable",
        "model_name": model_name,
        "months_used": months_used,
        "current_month_expense": round(current_month_expense, 2),
        "previous_month_expense": round(previous_month_expense, 2),
        "rolling_3_month_expense_avg": round(rolling_3_month_expense_avg, 2),
        "budget_total": round(budget_total, 2),
        "forecast_vs_budget": None,
        "top_reduction_categories": [],
        "recommendation": "Not enough clean spending history is available to forecast next month yet.",
    }


def _forecast_risk_message(top_categories: list[str]) -> str:
    first = top_categories[0] if top_categories else "your highest-spending"
    second = top_categories[1] if len(top_categories) > 1 else "other high-spending"
    return (
        "Your forecasted spending for next month may exceed your budget. "
        f"Consider reducing {first} and {second} expenses."
    )


def _recommendation(predicted: float, budget_total: float, top_categories: list[str]) -> str:
    if budget_total > 0 and predicted > budget_total:
        return _forecast_risk_message(top_categories)
    return (
        "Your forecasted spending appears to be within your current budget. "
        "Continue monitoring your highest spending categories."
    )


def _forecast_month_for_user(db: Session, user_id: int) -> date:
    latest_tx_date = db.query(func.max(Transaction.date)).filter(Transaction.user_id == user_id).scalar()
    if latest_tx_date is None:
        return normalize_month(date.today())
    return _shift_month(normalize_month(latest_tx_date), 1)


def _should_create_forecast_risk_insight(forecast: SpendingForecast) -> bool:
    if forecast["confidence_level"] == "unavailable":
        return False

    predicted = _optional_float(forecast.get("predicted_next_month_expense"))
    budget_total = _optional_float(forecast.get("budget_total"))
    forecast_vs_budget = _optional_float(forecast.get("forecast_vs_budget"))
    if predicted is None or budget_total is None or forecast_vs_budget is None:
        return False
    if budget_total <= 0 or predicted <= budget_total:
        return False

    meaningful_threshold = max(MEANINGFUL_OVER_BUDGET_FLOOR, budget_total * MEANINGFUL_OVER_BUDGET_RATIO)
    return forecast_vs_budget >= meaningful_threshold


def _forecast_risk_severity(forecast: SpendingForecast) -> Literal["warning", "critical"]:
    predicted = _optional_float(forecast.get("predicted_next_month_expense")) or 0.0
    budget_total = _optional_float(forecast.get("budget_total")) or 0.0
    if budget_total > 0 and predicted >= budget_total * CRITICAL_BUDGET_RATIO:
        return "critical"
    return "warning"


def _existing_forecast_risk_insight(
    db: Session,
    *,
    user_id: int,
    forecast_month: date,
    scope_key: str,
) -> AIInsight | None:
    existing = (
        db.query(AIInsight)
        .filter(
            AIInsight.user_id == user_id,
            AIInsight.rule_id == FORECAST_RISK_RULE_ID,
            AIInsight.period_start == forecast_month,
            AIInsight.period_end == _month_end(forecast_month),
        )
        .all()
    )
    return next(
        (
            insight
            for insight in existing
            if (insight.metadata_json or {}).get("scope_key") == scope_key
        ),
        None,
    )


def maybe_create_forecast_risk_insight(
    db: Session,
    *,
    user_id: int,
    forecast: SpendingForecast,
) -> AIInsight | None:
    if not _should_create_forecast_risk_insight(forecast):
        return None

    forecast_month = _forecast_month_for_user(db, user_id)
    scope_key = f"forecast_month:{forecast_month.isoformat()}"
    existing = _existing_forecast_risk_insight(
        db,
        user_id=user_id,
        forecast_month=forecast_month,
        scope_key=scope_key,
    )
    if existing is not None:
        return existing

    top_categories = list(forecast.get("top_reduction_categories") or [])
    insight = AIInsight(
        user_id=user_id,
        rule_id=FORECAST_RISK_RULE_ID,
        title="Forecasted Spending May Exceed Budget",
        message=_forecast_risk_message(top_categories),
        severity=_forecast_risk_severity(forecast),
        period_start=forecast_month,
        period_end=_month_end(forecast_month),
        metadata_json={
            "scope_key": scope_key,
            "predicted_next_month_expense": forecast.get("predicted_next_month_expense"),
            "budget_total": forecast.get("budget_total"),
            "forecast_vs_budget": forecast.get("forecast_vs_budget"),
            "confidence_level": forecast.get("confidence_level"),
            "top_reduction_categories": top_categories,
            "source": FORECAST_RISK_SOURCE,
        },
    )
    db.add(insight)
    db.commit()
    db.refresh(insight)
    return insight


class SpendingForecaster:
    def __init__(self, model_path: Path = MODEL_PATH) -> None:
        self.model_path = model_path
        self._model: Any | None = None
        self._feature_columns: list[str] = []
        self._model_name = DEFAULT_MODEL_NAME
        self._load_model()

    def _load_model(self) -> None:
        if not self.model_path.exists():
            logger.info("Spending forecaster model not found at %s", self.model_path)
            return

        try:
            artifact = joblib.load(self.model_path)
        except Exception:
            logger.exception("Failed to load spending forecaster model from %s", self.model_path)
            return

        if not isinstance(artifact, dict):
            logger.warning("Ignoring incompatible spending forecaster artifact at %s", self.model_path)
            return

        model = artifact.get("model")
        feature_columns = artifact.get("feature_columns")
        metadata = artifact.get("metadata") if isinstance(artifact.get("metadata"), dict) else {}
        model_family = metadata.get("model_family") or artifact.get("model_family")

        if model_family not in {None, MODEL_FAMILY}:
            logger.warning("Ignoring unsupported spending forecaster model family: %s", model_family)
            return
        if model is None or not hasattr(model, "predict"):
            logger.warning("Ignoring spending forecaster artifact without prediction support")
            return
        if not isinstance(feature_columns, list) or not all(isinstance(column, str) for column in feature_columns):
            logger.warning("Ignoring spending forecaster artifact without feature columns")
            return

        self._model = model
        self._feature_columns = feature_columns
        self._model_name = str(artifact.get("model_name") or metadata.get("model_name") or DEFAULT_MODEL_NAME)
        logger.info("Spending forecaster loaded from %s", self.model_path)

    def is_ready(self) -> bool:
        return self._model is not None and bool(self._feature_columns)

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
            metadata = insight.metadata_json or {}
            transaction_id = _optional_int(metadata.get("transaction_id"))
            if transaction_id is not None:
                transaction_ids.add(transaction_id)
        return transaction_ids

    def _budget_totals_by_month(self, db: Session, user_id: int) -> dict[date, float]:
        rows = (
            db.query(Budget.month, func.coalesce(func.sum(Budget.amount), 0.0))
            .filter(Budget.user_id == user_id)
            .group_by(Budget.month)
            .all()
        )
        budget_totals: dict[date, float] = defaultdict(float)
        for budget_month, amount in rows:
            budget_totals[normalize_month(budget_month)] += float(amount or 0.0)
        return dict(budget_totals)

    def _monthly_snapshots(self, db: Session, user_id: int) -> list[MonthSnapshot]:
        excluded_transaction_ids = self._unusual_transaction_ids(db, user_id)
        budget_totals = self._budget_totals_by_month(db, user_id)
        snapshots: dict[date, MonthSnapshot] = {}

        rows = (
            db.query(Transaction, Category.name)
            .join(Category, Category.category_id == Transaction.category_id)
            .filter(Transaction.user_id == user_id, Category.user_id == user_id)
            .order_by(Transaction.date.asc(), Transaction.transaction_id.asc())
            .all()
        )

        for tx, category_name in rows:
            if tx.transaction_id in excluded_transaction_ids:
                continue

            month_start = normalize_month(tx.date)
            snapshot = snapshots.setdefault(month_start, MonthSnapshot(month_start=month_start))
            transaction_type = str(tx.type or "").lower()
            amount = float(tx.amount or 0.0)

            snapshot.transaction_count += 1
            snapshot.category_ids.add(int(tx.category_id))
            if transaction_type == "income":
                snapshot.total_income += amount
                snapshot.income_transaction_count += 1
            elif transaction_type == "expense":
                snapshot.clean_total_expense += amount
                snapshot.expense_transaction_count += 1
                snapshot.expense_by_category[str(category_name or "Other")] += amount

        for month_start, snapshot in snapshots.items():
            snapshot.budget_total = float(budget_totals.get(month_start, 0.0))

        return sorted(snapshots.values(), key=lambda snapshot: snapshot.month_start)

    def _expense_for_month(self, snapshots_by_month: dict[date, MonthSnapshot], month_start: date) -> float:
        snapshot = snapshots_by_month.get(month_start)
        return float(snapshot.clean_total_expense if snapshot is not None else 0.0)

    def _rolling_expense_average(
        self,
        snapshots_by_month: dict[date, MonthSnapshot],
        latest_month: date,
        window: int,
    ) -> float:
        values = [
            self._expense_for_month(snapshots_by_month, _shift_month(latest_month, -offset))
            for offset in range(window)
        ]
        return sum(values) / len(values) if values else 0.0

    def _build_feature_row(self, snapshots: list[MonthSnapshot]) -> dict[str, float | str]:
        latest = snapshots[-1]
        first_month = snapshots[0].month_start
        snapshots_by_month = {snapshot.month_start: snapshot for snapshot in snapshots}

        previous_month_expense = self._expense_for_month(snapshots_by_month, _shift_month(latest.month_start, -1))
        expense_2_months_ago = self._expense_for_month(snapshots_by_month, _shift_month(latest.month_start, -2))
        rolling_3_month_expense_avg = self._rolling_expense_average(snapshots_by_month, latest.month_start, 3)
        rolling_6_month_expense_avg = self._rolling_expense_average(snapshots_by_month, latest.month_start, 6)
        expense_growth_rate = (
            (latest.clean_total_expense - previous_month_expense) / previous_month_expense
            if previous_month_expense > 0
            else 0.0
        )
        top_categories = latest.top_expense_categories

        values: dict[str, float | str] = {
            "business_profile": "small_business",
            "year": float(latest.month_start.year),
            "month": float(latest.month_start.month),
            "month_index": float(_month_delta(first_month, latest.month_start)),
            "total_income": latest.total_income,
            "clean_total_expense": latest.clean_total_expense,
            "budget_total": latest.budget_total,
            "transaction_count": float(latest.transaction_count),
            "expense_transaction_count": float(latest.expense_transaction_count),
            "income_transaction_count": float(latest.income_transaction_count),
            "category_count": float(latest.category_count),
            "previous_month_expense": previous_month_expense,
            "expense_2_months_ago": expense_2_months_ago,
            "rolling_3_month_expense_avg": rolling_3_month_expense_avg,
            "rolling_6_month_expense_avg": rolling_6_month_expense_avg,
            "expense_growth_rate": expense_growth_rate,
            "expense_to_income_ratio": latest.expense_to_income_ratio,
            "budget_usage_ratio": latest.budget_usage_ratio,
            "budget_exceeded": latest.budget_exceeded,
            "top_spend_category_1": top_categories[0] if len(top_categories) >= 1 else "unknown",
            "top_spend_category_2": top_categories[1] if len(top_categories) >= 2 else "unknown",
            "top_spend_category_3": top_categories[2] if len(top_categories) >= 3 else "unknown",
        }

        feature_row: dict[str, float | str] = {}
        for column in self._feature_columns:
            default_value: float | str = "unknown" if column in {"business_profile", "top_spend_category_1", "top_spend_category_2", "top_spend_category_3"} else 0.0
            feature_row[column] = values.get(column, default_value)
        return feature_row

    def forecast_for_user(self, db: Session, user_id: int) -> SpendingForecast:
        if not self.is_ready():
            return _unavailable_response(model_name=self._model_name)

        try:
            snapshots = self._monthly_snapshots(db, user_id)
            months_used = len(snapshots)
            if months_used < 2:
                current = snapshots[-1] if snapshots else None
                return _unavailable_response(
                    model_name=self._model_name,
                    months_used=months_used,
                    current_month_expense=float(current.clean_total_expense if current else 0.0),
                    budget_total=float(current.budget_total if current else 0.0),
                )

            latest = snapshots[-1]
            snapshots_by_month = {snapshot.month_start: snapshot for snapshot in snapshots}
            previous_month_expense = self._expense_for_month(snapshots_by_month, _shift_month(latest.month_start, -1))
            rolling_3_month_expense_avg = self._rolling_expense_average(snapshots_by_month, latest.month_start, 3)
            feature_row = self._build_feature_row(snapshots)

            assert self._model is not None
            prediction = _safe_prediction_value(self._model.predict([feature_row])[0])
            if months_used >= 6:
                confidence: ConfidenceLevel = "high"
            elif months_used >= 4:
                confidence = "medium"
            else:
                confidence = "low"
            top_reduction_categories = latest.top_expense_categories[:2]
            forecast_vs_budget = prediction - latest.budget_total

            return {
                "predicted_next_month_expense": round(prediction, 2),
                "confidence_level": confidence,
                "model_name": self._model_name,
                "months_used": months_used,
                "current_month_expense": round(latest.clean_total_expense, 2),
                "previous_month_expense": round(previous_month_expense, 2),
                "rolling_3_month_expense_avg": round(rolling_3_month_expense_avg, 2),
                "budget_total": round(latest.budget_total, 2),
                "forecast_vs_budget": round(forecast_vs_budget, 2),
                "top_reduction_categories": top_reduction_categories,
                "recommendation": _recommendation(prediction, latest.budget_total, top_reduction_categories),
            }
        except Exception:
            logger.exception("Spending forecast failed for user %s", user_id)
            return _unavailable_response(model_name=self._model_name)


forecaster = SpendingForecaster()


def is_ready() -> bool:
    return forecaster.is_ready()


def forecast_for_user(db: Session, user_id: int) -> SpendingForecast:
    return forecaster.forecast_for_user(db, user_id)
