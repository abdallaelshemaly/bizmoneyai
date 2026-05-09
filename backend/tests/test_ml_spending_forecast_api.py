from __future__ import annotations

from datetime import date

from fastapi.testclient import TestClient

import app.api.ml as ml_api
from app.core.security import create_access_token
from app.db.session import get_db
from app.main import app
from app.models.ai_insight import AIInsight
from app.models.budget import Budget
from app.models.category import Category
from app.models.transaction import Transaction
from app.models.user import User
from app.services.spending_forecaster import DEFAULT_MODEL_NAME, SpendingForecaster


class FakeSpendingForecaster:
    def __init__(self, response: dict):
        self.response = response
        self.calls: list[tuple[int]] = []

    def forecast_for_user(self, db, user_id: int) -> dict:
        self.calls.append((user_id,))
        return self.response


def _authenticated_client(db_session):
    user = User(
        name="Spending Forecast API User",
        email="spending-forecast-api@example.com",
        password_hash="x",
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)

    app.dependency_overrides[get_db] = lambda: db_session
    client = TestClient(app)
    client.cookies.set("access_token", create_access_token(str(user.user_id)))
    return client, user


def _service_backed_client(db_session, monkeypatch, forecaster: SpendingForecaster):
    user = User(
        name="Spending Forecast Service User",
        email="spending-forecast-service@example.com",
        password_hash="x",
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)

    income = Category(user_id=user.user_id, name="Sales", type="income")
    marketing = Category(user_id=user.user_id, name="Marketing", type="expense")
    software = Category(user_id=user.user_id, name="Software", type="expense")
    db_session.add_all([income, marketing, software])
    db_session.commit()
    db_session.refresh(income)
    db_session.refresh(marketing)
    db_session.refresh(software)

    monkeypatch.setattr(ml_api, "spending_forecaster", forecaster)
    app.dependency_overrides[get_db] = lambda: db_session
    client = TestClient(app)
    client.cookies.set("access_token", create_access_token(str(user.user_id)))
    return client, user, income, marketing, software


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


def test_forecast_spending_requires_auth(db_session):
    app.dependency_overrides[get_db] = lambda: db_session
    client = TestClient(app)

    try:
        response = client.get("/ml/forecast-spending")
        assert response.status_code == 401
    finally:
        app.dependency_overrides.clear()


def test_forecast_spending_returns_expected_schema(db_session, monkeypatch):
    fake_forecaster = FakeSpendingForecaster(
        {
            "predicted_next_month_expense": 850.0,
            "confidence_level": "medium",
            "model_name": DEFAULT_MODEL_NAME,
            "months_used": 4,
            "current_month_expense": 600.0,
            "previous_month_expense": 500.0,
            "rolling_3_month_expense_avg": 550.0,
            "budget_total": 700.0,
            "forecast_vs_budget": 150.0,
            "top_reduction_categories": ["Marketing", "Software"],
            "recommendation": "Your forecasted spending for next month may exceed your budget. Consider reducing Marketing and Software expenses.",
        }
    )
    monkeypatch.setattr(ml_api, "spending_forecaster", fake_forecaster)
    client, user = _authenticated_client(db_session)

    try:
        response = client.get("/ml/forecast-spending")

        assert response.status_code == 200
        body = response.json()
        assert set(body.keys()) == {
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
        assert body["confidence_level"] == "medium"
        assert body["model_name"] == DEFAULT_MODEL_NAME
        assert fake_forecaster.calls == [(user.user_id,)]
    finally:
        app.dependency_overrides.clear()


def test_forecast_spending_works_when_model_is_available(db_session, monkeypatch):
    fake_forecaster = FakeSpendingForecaster(
        {
            "predicted_next_month_expense": 720.5,
            "confidence_level": "high",
            "model_name": DEFAULT_MODEL_NAME,
            "months_used": 7,
            "current_month_expense": 680.0,
            "previous_month_expense": 640.0,
            "rolling_3_month_expense_avg": 650.0,
            "budget_total": 800.0,
            "forecast_vs_budget": -79.5,
            "top_reduction_categories": ["Marketing", "Software"],
            "recommendation": "Your forecasted spending appears to be within your current budget. Continue monitoring your highest spending categories.",
        }
    )
    monkeypatch.setattr(ml_api, "spending_forecaster", fake_forecaster)
    client, _user = _authenticated_client(db_session)

    try:
        response = client.get("/ml/forecast-spending")
        assert response.status_code == 200
        assert response.json()["predicted_next_month_expense"] == 720.5
    finally:
        app.dependency_overrides.clear()


def test_forecast_spending_fails_safely_when_model_unavailable(db_session, monkeypatch):
    fake_forecaster = FakeSpendingForecaster(
        {
            "predicted_next_month_expense": None,
            "confidence_level": "unavailable",
            "model_name": DEFAULT_MODEL_NAME,
            "months_used": 0,
            "current_month_expense": 0.0,
            "previous_month_expense": 0.0,
            "rolling_3_month_expense_avg": 0.0,
            "budget_total": 0.0,
            "forecast_vs_budget": None,
            "top_reduction_categories": [],
            "recommendation": "Not enough clean spending history is available to forecast next month yet.",
        }
    )
    monkeypatch.setattr(ml_api, "spending_forecaster", fake_forecaster)
    client, _user = _authenticated_client(db_session)

    try:
        response = client.get("/ml/forecast-spending")
        assert response.status_code == 200
        assert response.json()["confidence_level"] == "unavailable"
    finally:
        app.dependency_overrides.clear()


def test_forecast_spending_excludes_unusual_transactions_via_api_path(db_session, monkeypatch, tmp_path):
    model_path = tmp_path / "missing.joblib"
    forecaster = SpendingForecaster(model_path=model_path)
    forecaster._model = type("EchoModel", (), {"predict": lambda self, rows: [float(rows[0]["clean_total_expense"])]})()
    forecaster._feature_columns = [
        "business_profile",
        "year",
        "month",
        "month_index",
        "total_income",
        "clean_total_expense",
        "budget_total",
        "transaction_count",
        "expense_transaction_count",
        "income_transaction_count",
        "category_count",
        "previous_month_expense",
        "expense_2_months_ago",
        "rolling_3_month_expense_avg",
        "rolling_6_month_expense_avg",
        "expense_growth_rate",
        "expense_to_income_ratio",
        "budget_usage_ratio",
        "budget_exceeded",
        "top_spend_category_1",
        "top_spend_category_2",
        "top_spend_category_3",
    ]
    forecaster._model_name = DEFAULT_MODEL_NAME

    client, user, income, marketing, software = _service_backed_client(db_session, monkeypatch, forecaster)
    _add_transaction(db_session, user=user, category=income, amount=3000.0, tx_type="income", tx_date=date(2026, 4, 1))
    _add_transaction(db_session, user=user, category=marketing, amount=200.0, tx_type="expense", tx_date=date(2026, 4, 2))
    _add_budget(db_session, user=user, category=marketing, amount=500.0, month=date(2026, 4, 1))
    _add_transaction(db_session, user=user, category=income, amount=3000.0, tx_type="income", tx_date=date(2026, 5, 1))
    _add_transaction(db_session, user=user, category=marketing, amount=100.0, tx_type="expense", tx_date=date(2026, 5, 2))
    unusual_tx = _add_transaction(
        db_session,
        user=user,
        category=software,
        amount=10000.0,
        tx_type="expense",
        tx_date=date(2026, 5, 3),
    )
    _add_budget(db_session, user=user, category=marketing, amount=500.0, month=date(2026, 5, 1))
    _add_unusual_insight(db_session, user=user, tx=unusual_tx, severity="critical")
    db_session.commit()

    try:
        response = client.get("/ml/forecast-spending")
        assert response.status_code == 200
        body = response.json()
        assert body["current_month_expense"] == 100.0
        assert body["predicted_next_month_expense"] == 100.0
    finally:
        app.dependency_overrides.clear()


def test_forecast_spending_recommendation_is_present(db_session, monkeypatch):
    fake_forecaster = FakeSpendingForecaster(
        {
            "predicted_next_month_expense": 900.0,
            "confidence_level": "low",
            "model_name": DEFAULT_MODEL_NAME,
            "months_used": 2,
            "current_month_expense": 500.0,
            "previous_month_expense": 300.0,
            "rolling_3_month_expense_avg": 400.0,
            "budget_total": 600.0,
            "forecast_vs_budget": 300.0,
            "top_reduction_categories": ["Marketing", "Software"],
            "recommendation": "Your forecasted spending for next month may exceed your budget. Consider reducing Marketing and Software expenses.",
        }
    )
    monkeypatch.setattr(ml_api, "spending_forecaster", fake_forecaster)
    client, _user = _authenticated_client(db_session)

    try:
        response = client.get("/ml/forecast-spending")
        assert response.status_code == 200
        assert isinstance(response.json()["recommendation"], str)
        assert response.json()["recommendation"]
    finally:
        app.dependency_overrides.clear()
