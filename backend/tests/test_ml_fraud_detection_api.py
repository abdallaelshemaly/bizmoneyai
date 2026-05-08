from __future__ import annotations

from fastapi.testclient import TestClient

import app.api.ml as ml_api
from app.core.security import create_access_token
from app.db.session import get_db
from app.main import app
from app.models.user import User


class FakeFraudDetector:
    def __init__(self, response):
        self.response = response
        self.last_payload = None

    def predict(self, payload: dict):
        self.last_payload = payload
        return self.response


def _authenticated_client(db_session):
    user = User(
        name="Fraud API Test User",
        email="fraud-api-test@example.com",
        password_hash="x",
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)

    app.dependency_overrides[get_db] = lambda: db_session
    client = TestClient(app)
    client.cookies.set("access_token", create_access_token(str(user.user_id)))
    return client


def test_detect_unusual_transaction_requires_auth(db_session):
    app.dependency_overrides[get_db] = lambda: db_session
    client = TestClient(app)

    try:
        response = client.post(
            "/ml/detect-unusual-transaction",
            json={"amount": 1000, "transaction_type": "PAYMENT"},
        )

        assert response.status_code == 401
    finally:
        app.dependency_overrides.clear()


def test_detect_unusual_transaction_returns_expected_schema(db_session, monkeypatch):
    fake_detector = FakeFraudDetector(
        {
            "is_unusual": True,
            "fraud_probability": 0.87,
            "risk_level": "critical",
            "model_name": "Fake Fraud Detector",
        }
    )
    monkeypatch.setattr(ml_api, "fraud_detector", fake_detector)
    client = _authenticated_client(db_session)

    try:
        response = client.post(
            "/ml/detect-unusual-transaction",
            json={
                "amount": 7500,
                "transaction_type": "expense",
                "category_name": "Marketing",
                "description": "Urgent campaign settlement",
                "date": "2026-04-25",
                "budget_amount": 4000,
                "budget_spent_before": 3900,
                "budget_usage_ratio": 0.975,
                "user_avg_amount": 1200,
                "category_avg_amount": 1100,
                "recent_transaction_count": 1,
            },
        )

        assert response.status_code == 200
        body = response.json()
        assert set(body.keys()) == {
            "is_unusual",
            "fraud_probability",
            "risk_level",
            "model_name",
        }
        assert body == {
            "is_unusual": True,
            "fraud_probability": 0.87,
            "risk_level": "critical",
            "model_name": "Fake Fraud Detector",
        }
        assert fake_detector.last_payload == {
            "amount": 7500.0,
            "type": "expense",
            "category_name": "Marketing",
            "description": "Urgent campaign settlement",
            "date": "2026-04-25",
            "budget_amount": 4000.0,
            "budget_spent_before": 3900.0,
            "budget_usage_ratio": 0.975,
            "user_avg_amount": 1200.0,
            "category_avg_amount": 1100.0,
            "recent_transaction_count": 1,
        }
    finally:
        app.dependency_overrides.clear()


def test_detect_unusual_transaction_works_when_model_unavailable(db_session, monkeypatch):
    monkeypatch.setattr(
        ml_api,
        "fraud_detector",
        FakeFraudDetector(
            {
                "is_unusual": False,
                "fraud_probability": 0.0,
                "risk_level": "normal",
                "model_name": "BizMoneyAI Model 2 Fraud Detector",
            }
        ),
    )
    client = _authenticated_client(db_session)

    try:
        response = client.post(
            "/ml/detect-unusual-transaction",
            json={"amount": 25.5, "transaction_type": "expense"},
        )

        assert response.status_code == 200
        assert response.json() == {
            "is_unusual": False,
            "fraud_probability": 0.0,
            "risk_level": "normal",
            "model_name": "BizMoneyAI Model 2 Fraud Detector",
        }
    finally:
        app.dependency_overrides.clear()
