from __future__ import annotations

from datetime import date

from fastapi.testclient import TestClient

import app.api.ml as ml_api
from app.core.security import create_access_token
from app.db.session import get_db
from app.main import app
from app.models.ai_insight import AIInsight
from app.models.category import Category
from app.models.transaction import Transaction
from app.models.user import User
from app.services.spending_forecaster import (
    DEFAULT_MODEL_NAME,
    FORECAST_RISK_RULE_ID,
)


def _create_user_with_history(db_session):
    user = User(name="Forecast Insight User", email="forecast-insight@example.com", password_hash="x")
    db_session.add(user)
    db_session.flush()

    income = Category(user_id=user.user_id, name="Sales", type="income")
    marketing = Category(user_id=user.user_id, name="Marketing", type="expense")
    db_session.add_all([income, marketing])
    db_session.flush()

    db_session.add_all(
        [
            Transaction(
                user_id=user.user_id,
                category_id=income.category_id,
                amount=3000.0,
                type="income",
                description="Client payment",
                date=date(2026, 5, 1),
            ),
            Transaction(
                user_id=user.user_id,
                category_id=marketing.category_id,
                amount=300.0,
                type="expense",
                description="Campaign spend",
                date=date(2026, 5, 2),
            ),
        ]
    )
    db_session.commit()
    db_session.refresh(user)
    return user


def _client_for_user(db_session, user: User) -> TestClient:
    app.dependency_overrides[get_db] = lambda: db_session
    client = TestClient(app)
    client.cookies.set("access_token", create_access_token(str(user.user_id)))
    return client


def _forecast_response(
    *,
    predicted: float | None = 700.0,
    budget_total: float = 500.0,
    forecast_vs_budget: float | None = 200.0,
    confidence_level: str = "medium",
) -> dict:
    return {
        "predicted_next_month_expense": predicted,
        "confidence_level": confidence_level,
        "model_name": DEFAULT_MODEL_NAME,
        "months_used": 4,
        "current_month_expense": 500.0,
        "previous_month_expense": 450.0,
        "rolling_3_month_expense_avg": 475.0,
        "budget_total": budget_total,
        "forecast_vs_budget": forecast_vs_budget,
        "top_reduction_categories": ["Marketing", "Software"],
        "recommendation": (
            "Your forecasted spending for next month may exceed your budget. "
            "Consider reducing Marketing and Software expenses."
        ),
    }


def _patch_forecast(monkeypatch, forecast: dict) -> None:
    monkeypatch.setattr(ml_api.spending_forecaster, "forecast_for_user", lambda db, user_id: forecast)


def test_forecast_risk_insight_is_created_when_forecast_exceeds_budget(db_session, monkeypatch):
    user = _create_user_with_history(db_session)
    _patch_forecast(monkeypatch, _forecast_response())
    client = _client_for_user(db_session, user)

    try:
        response = client.get("/ml/forecast-spending")
        assert response.status_code == 200

        insight = db_session.query(AIInsight).filter(AIInsight.user_id == user.user_id).one()
        assert insight.rule_id == FORECAST_RISK_RULE_ID
        assert insight.severity == "warning"
        assert insight.period_start == date(2026, 6, 1)
        assert insight.message == (
            "Your forecasted spending for next month may exceed your budget. "
            "Consider reducing Marketing and Software expenses."
        )
        assert insight.metadata_json is not None
        assert insight.metadata_json["predicted_next_month_expense"] == 700.0
        assert insight.metadata_json["budget_total"] == 500.0
        assert insight.metadata_json["forecast_vs_budget"] == 200.0
        assert insight.metadata_json["confidence_level"] == "medium"
        assert insight.metadata_json["top_reduction_categories"] == ["Marketing", "Software"]
        assert insight.metadata_json["source"] == "spending_forecaster"
        assert insight.metadata_json["scope_key"] == "forecast_month:2026-06-01"
    finally:
        app.dependency_overrides.clear()


def test_forecast_risk_insight_is_not_duplicated_on_refresh(db_session, monkeypatch):
    user = _create_user_with_history(db_session)
    _patch_forecast(monkeypatch, _forecast_response())
    client = _client_for_user(db_session, user)

    try:
        assert client.get("/ml/forecast-spending").status_code == 200
        assert client.get("/ml/forecast-spending").status_code == 200

        count = (
            db_session.query(AIInsight)
            .filter(AIInsight.user_id == user.user_id, AIInsight.rule_id == FORECAST_RISK_RULE_ID)
            .count()
        )
        assert count == 1
    finally:
        app.dependency_overrides.clear()


def test_forecast_risk_insight_is_not_created_when_forecast_is_within_budget(db_session, monkeypatch):
    user = _create_user_with_history(db_session)
    _patch_forecast(
        monkeypatch,
        _forecast_response(predicted=450.0, budget_total=500.0, forecast_vs_budget=-50.0),
    )
    client = _client_for_user(db_session, user)

    try:
        assert client.get("/ml/forecast-spending").status_code == 200
        assert db_session.query(AIInsight).filter(AIInsight.user_id == user.user_id).count() == 0
    finally:
        app.dependency_overrides.clear()


def test_forecast_risk_insight_is_not_created_when_confidence_is_unavailable(db_session, monkeypatch):
    user = _create_user_with_history(db_session)
    _patch_forecast(
        monkeypatch,
        _forecast_response(
            predicted=None,
            budget_total=500.0,
            forecast_vs_budget=None,
            confidence_level="unavailable",
        ),
    )
    client = _client_for_user(db_session, user)

    try:
        assert client.get("/ml/forecast-spending").status_code == 200
        assert db_session.query(AIInsight).filter(AIInsight.user_id == user.user_id).count() == 0
    finally:
        app.dependency_overrides.clear()


def test_forecast_risk_insight_appears_in_ai_insights_page_data(db_session, monkeypatch):
    user = _create_user_with_history(db_session)
    _patch_forecast(monkeypatch, _forecast_response())
    client = _client_for_user(db_session, user)

    try:
        assert client.get("/ml/forecast-spending").status_code == 200

        response = client.get("/ai/insights")
        assert response.status_code == 200
        body = response.json()
        assert len(body) == 1
        assert body[0]["rule_id"] == FORECAST_RISK_RULE_ID
        assert body[0]["message"] == (
            "Your forecasted spending for next month may exceed your budget. "
            "Consider reducing Marketing and Software expenses."
        )
    finally:
        app.dependency_overrides.clear()
