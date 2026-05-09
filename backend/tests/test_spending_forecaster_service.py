from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

import joblib

from app.ml.forecasting.train_spending_forecaster import FEATURE_COLUMNS
from app.models.ai_insight import AIInsight
from app.models.budget import Budget
from app.models.category import Category
from app.models.transaction import Transaction
from app.models.user import User
from app.services.spending_forecaster import (
    DEFAULT_MODEL_NAME,
    MODEL_FAMILY,
    SpendingForecaster,
)


class ConstantForecastModel:
    def __init__(self, prediction: float) -> None:
        self.prediction = prediction

    def predict(self, rows: list[dict[str, Any]]) -> list[float]:
        return [self.prediction for _row in rows]


class CleanExpenseEchoModel:
    def predict(self, rows: list[dict[str, Any]]) -> list[float]:
        return [float(row["clean_total_expense"]) for row in rows]


def _write_artifact(tmp_path: Path, model: object) -> Path:
    model_path = tmp_path / "spending_forecaster.joblib"
    joblib.dump(
        {
            "model": model,
            "model_name": DEFAULT_MODEL_NAME,
            "model_family": MODEL_FAMILY,
            "feature_columns": FEATURE_COLUMNS,
        },
        model_path,
    )
    return model_path


def _create_user(db_session):
    user = User(name="Forecast User", email="forecast@example.com", password_hash="x")
    db_session.add(user)
    db_session.flush()

    income = Category(user_id=user.user_id, name="Sales", type="income")
    marketing = Category(user_id=user.user_id, name="Marketing", type="expense")
    software = Category(user_id=user.user_id, name="Software", type="expense")
    db_session.add_all([income, marketing, software])
    db_session.flush()
    return user, income, marketing, software


def _add_transaction(
    db_session,
    *,
    user: User,
    category: Category,
    amount: float,
    tx_type: str,
    tx_date: date,
) -> Transaction:
    tx = Transaction(
        user_id=user.user_id,
        category_id=category.category_id,
        amount=amount,
        type=tx_type,
        description=f"{category.name} transaction",
        date=tx_date,
    )
    db_session.add(tx)
    db_session.flush()
    return tx


def _add_budget(db_session, *, user: User, category: Category, amount: float, month: date) -> None:
    db_session.add(
        Budget(
            user_id=user.user_id,
            category_id=category.category_id,
            amount=amount,
            month=month,
        )
    )


def _add_unusual_insight(db_session, *, user: User, tx: Transaction, severity: str = "warning") -> None:
    db_session.add(
        AIInsight(
            user_id=user.user_id,
            rule_id="ml_unusual_transaction",
            title="Unusual Transaction Detected",
            message="Unusual transaction detected.",
            severity=severity,
            period_start=tx.date,
            period_end=tx.date,
            metadata_json={"transaction_id": tx.transaction_id},
        )
    )


def _add_month(
    db_session,
    *,
    user: User,
    income: Category,
    marketing: Category,
    software: Category,
    month: date,
    marketing_amount: float,
    software_amount: float = 0.0,
    budget_total: float = 1000.0,
) -> None:
    _add_transaction(db_session, user=user, category=income, amount=3000.0, tx_type="income", tx_date=month)
    _add_transaction(db_session, user=user, category=marketing, amount=marketing_amount, tx_type="expense", tx_date=month)
    if software_amount > 0:
        _add_transaction(db_session, user=user, category=software, amount=software_amount, tx_type="expense", tx_date=month)
    _add_budget(db_session, user=user, category=marketing, amount=budget_total, month=month)


def test_service_loads_model(tmp_path: Path) -> None:
    forecaster = SpendingForecaster(model_path=_write_artifact(tmp_path, ConstantForecastModel(500.0)))

    assert forecaster.is_ready() is True


def test_service_fails_safely_when_artifact_missing(db_session, tmp_path: Path) -> None:
    forecaster = SpendingForecaster(model_path=tmp_path / "missing.joblib")

    result = forecaster.forecast_for_user(db_session, user_id=123)

    assert forecaster.is_ready() is False
    assert result["confidence_level"] == "unavailable"
    assert result["predicted_next_month_expense"] is None


def test_service_returns_unavailable_for_too_little_history(db_session, tmp_path: Path) -> None:
    forecaster = SpendingForecaster(model_path=_write_artifact(tmp_path, ConstantForecastModel(500.0)))
    user, income, marketing, _software = _create_user(db_session)
    _add_transaction(db_session, user=user, category=income, amount=3000.0, tx_type="income", tx_date=date(2026, 5, 1))
    _add_transaction(db_session, user=user, category=marketing, amount=250.0, tx_type="expense", tx_date=date(2026, 5, 2))
    db_session.commit()

    result = forecaster.forecast_for_user(db_session, user.user_id)

    assert result["confidence_level"] == "unavailable"
    assert result["months_used"] == 1
    assert result["predicted_next_month_expense"] is None
    assert result["current_month_expense"] == 250.0


def test_service_excludes_warning_or_critical_unusual_transactions(db_session, tmp_path: Path) -> None:
    forecaster = SpendingForecaster(model_path=_write_artifact(tmp_path, CleanExpenseEchoModel()))
    user, income, marketing, software = _create_user(db_session)
    _add_month(
        db_session,
        user=user,
        income=income,
        marketing=marketing,
        software=software,
        month=date(2026, 4, 1),
        marketing_amount=200.0,
    )
    _add_transaction(db_session, user=user, category=income, amount=3000.0, tx_type="income", tx_date=date(2026, 5, 1))
    _add_transaction(db_session, user=user, category=marketing, amount=100.0, tx_type="expense", tx_date=date(2026, 5, 2))
    unusual_tx = _add_transaction(
        db_session,
        user=user,
        category=software,
        amount=10_000.0,
        tx_type="expense",
        tx_date=date(2026, 5, 3),
    )
    _add_budget(db_session, user=user, category=marketing, amount=500.0, month=date(2026, 5, 1))
    _add_unusual_insight(db_session, user=user, tx=unusual_tx, severity="warning")
    db_session.commit()

    result = forecaster.forecast_for_user(db_session, user.user_id)

    assert result["confidence_level"] == "low"
    assert result["current_month_expense"] == 100.0
    assert result["predicted_next_month_expense"] == 100.0
    assert result["top_reduction_categories"] == ["Marketing"]


def test_service_returns_forecast_schema(db_session, tmp_path: Path) -> None:
    forecaster = SpendingForecaster(model_path=_write_artifact(tmp_path, ConstantForecastModel(450.0)))
    user, income, marketing, software = _create_user(db_session)
    for month, amount in [
        (date(2026, 2, 1), 200.0),
        (date(2026, 3, 1), 250.0),
        (date(2026, 4, 1), 300.0),
        (date(2026, 5, 1), 350.0),
    ]:
        _add_month(
            db_session,
            user=user,
            income=income,
            marketing=marketing,
            software=software,
            month=month,
            marketing_amount=amount,
        )
    db_session.commit()

    result = forecaster.forecast_for_user(db_session, user.user_id)

    assert set(result.keys()) == {
        "predicted_next_month_expense",
        "confidence_level",
        "model_name",
        "months_used",
        "current_month_expense",
        "previous_month_expense",
        "rolling_3_month_expense_avg",
        "budget_total",
        "forecast_vs_budget",
        "top_reduction_categories",
        "recommendation",
    }
    assert isinstance(result["predicted_next_month_expense"], float)
    assert result["predicted_next_month_expense"] >= 0.0
    assert result["confidence_level"] == "medium"
    assert result["model_name"] == DEFAULT_MODEL_NAME


def test_recommendation_mentions_top_categories_when_forecast_exceeds_budget(db_session, tmp_path: Path) -> None:
    forecaster = SpendingForecaster(model_path=_write_artifact(tmp_path, ConstantForecastModel(900.0)))
    user, income, marketing, software = _create_user(db_session)
    _add_month(
        db_session,
        user=user,
        income=income,
        marketing=marketing,
        software=software,
        month=date(2026, 4, 1),
        marketing_amount=150.0,
        software_amount=50.0,
        budget_total=1000.0,
    )
    _add_month(
        db_session,
        user=user,
        income=income,
        marketing=marketing,
        software=software,
        month=date(2026, 5, 1),
        marketing_amount=300.0,
        software_amount=200.0,
        budget_total=500.0,
    )
    db_session.commit()

    result = forecaster.forecast_for_user(db_session, user.user_id)

    assert result["forecast_vs_budget"] == 400.0
    assert result["top_reduction_categories"] == ["Marketing", "Software"]
    assert (
        result["recommendation"]
        == "Your forecasted spending for next month may exceed your budget. Consider reducing Marketing and Software expenses."
    )
