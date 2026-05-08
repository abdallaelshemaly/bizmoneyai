from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import app.api.transactions as transactions_api
from app.core.security import create_access_token
from app.db.session import get_db
from app.main import app
from app.models.ai_insight import AIInsight
from app.models.category import Category
from app.models.system_log import SystemLog
from app.models.transaction import Transaction
from app.models.user import User


class FakeFraudDetector:
    def __init__(self, *, ready: bool, response: dict | None = None) -> None:
        self.ready = ready
        self.response = response or {
            "is_unusual": False,
            "fraud_probability": 0.0,
            "risk_level": "normal",
            "model_name": "Fake Fraud Detector",
        }
        self.payloads: list[dict] = []

    def is_ready(self) -> bool:
        return self.ready

    def predict(self, payload: dict) -> dict:
        self.payloads.append(payload)
        return self.response


def _client_with_expense_category(db_session):
    user = User(
        name="Transaction Fraud User",
        email="transaction-fraud@example.com",
        password_hash="x",
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)

    category = Category(user_id=user.user_id, name="Operations", type="expense")
    db_session.add(category)
    db_session.commit()
    db_session.refresh(category)

    app.dependency_overrides[get_db] = lambda: db_session
    client = TestClient(app)
    client.cookies.set("access_token", create_access_token(str(user.user_id)))
    return client, user, category


def _create_transaction(client: TestClient, category: Category, amount: float = 125.0):
    return client.post(
        "/transactions",
        json={
            "category_id": category.category_id,
            "amount": amount,
            "type": "expense",
            "description": "Vendor payment",
            "date": "2026-04-10",
        },
    )


def test_transaction_still_creates_if_detector_unavailable(db_session, monkeypatch):
    fake_detector = FakeFraudDetector(ready=False)
    monkeypatch.setattr(transactions_api, "fraud_detector", fake_detector)
    client, user, category = _client_with_expense_category(db_session)

    try:
        response = _create_transaction(client, category)

        assert response.status_code == 201
        assert db_session.query(Transaction).filter(Transaction.user_id == user.user_id).count() == 1
        assert db_session.query(AIInsight).filter(AIInsight.user_id == user.user_id).count() == 0
        assert fake_detector.payloads == []
    finally:
        app.dependency_overrides.clear()


@pytest.mark.parametrize(
    ("risk_level", "probability", "expected_message"),
    [
        (
            "warning",
            0.67,
            "Unusual transaction detected. This transaction appears higher risk than normal.",
        ),
        (
            "critical",
            0.91,
            "Critical unusual transaction detected. Review this transaction immediately.",
        ),
    ],
)
def test_warning_or_critical_result_creates_ai_insight(
    db_session,
    monkeypatch,
    risk_level,
    probability,
    expected_message,
):
    fake_detector = FakeFraudDetector(
        ready=True,
        response={
            "is_unusual": True,
            "fraud_probability": probability,
            "risk_level": risk_level,
            "model_name": "Fake Fraud Detector",
        },
    )
    monkeypatch.setattr(transactions_api, "fraud_detector", fake_detector)
    client, user, category = _client_with_expense_category(db_session)

    try:
        response = _create_transaction(client, category, amount=5000)

        assert response.status_code == 201
        response_body = response.json()
        transaction_id = response_body["transaction_id"]
        assert response_body["fraud_risk_level"] == risk_level
        assert response_body["fraud_probability"] == probability

        insight = db_session.query(AIInsight).filter(AIInsight.user_id == user.user_id).one()
        assert insight.rule_id == "ml_unusual_transaction"
        assert insight.severity == risk_level
        assert insight.message == expected_message
        assert insight.metadata_json is not None
        assert insight.metadata_json["transaction_id"] == transaction_id
        assert insight.metadata_json["risk_level"] == risk_level
        assert insight.metadata_json["fraud_probability"] == probability

        unusual_log = (
            db_session.query(SystemLog)
            .filter(
                SystemLog.user_id == user.user_id,
                SystemLog.event_type == "unusual_transaction_detected",
            )
            .one()
        )
        assert unusual_log.metadata_json is not None
        assert unusual_log.metadata_json["transaction_id"] == transaction_id
        assert unusual_log.metadata_json["risk_level"] == risk_level
        assert unusual_log.metadata_json["probability"] == probability
        assert fake_detector.payloads == [
            {
                "amount": 5000.0,
                "type": "CASH_OUT",
                "step": 0,
            }
        ]

        list_response = client.get("/transactions")
        assert list_response.status_code == 200
        list_body = list_response.json()
        assert list_body[0]["transaction_id"] == transaction_id
        assert list_body[0]["fraud_risk_level"] == risk_level
        assert list_body[0]["fraud_probability"] == probability
        assert list_body[0]["fraud_insight_id"] == insight.insight_id
    finally:
        app.dependency_overrides.clear()


def test_normal_result_does_not_create_ai_insight(db_session, monkeypatch):
    fake_detector = FakeFraudDetector(
        ready=True,
        response={
            "is_unusual": False,
            "fraud_probability": 0.03,
            "risk_level": "normal",
            "model_name": "Fake Fraud Detector",
        },
    )
    monkeypatch.setattr(transactions_api, "fraud_detector", fake_detector)
    client, user, category = _client_with_expense_category(db_session)

    try:
        response = _create_transaction(client, category)

        assert response.status_code == 201
        assert db_session.query(AIInsight).filter(AIInsight.user_id == user.user_id).count() == 0
        assert (
            db_session.query(SystemLog)
            .filter(
                SystemLog.user_id == user.user_id,
                SystemLog.event_type == "unusual_transaction_detected",
            )
            .count()
            == 0
        )
        assert len(fake_detector.payloads) == 1
    finally:
        app.dependency_overrides.clear()


def test_imported_warning_or_critical_transaction_creates_ai_insight(db_session, monkeypatch):
    fake_detector = FakeFraudDetector(
        ready=True,
        response={
            "is_unusual": True,
            "fraud_probability": 0.88,
            "risk_level": "critical",
            "model_name": "Fake Fraud Detector",
        },
    )
    monkeypatch.setattr(transactions_api, "fraud_detector", fake_detector)
    client, user, category = _client_with_expense_category(db_session)

    try:
        response = client.post(
            "/transactions/import-csv",
            files={
                "file": (
                    "transactions.csv",
                    (
                        "category_id,amount,type,description,date\n"
                        f"{category.category_id},45000,expense,Emergency vendor transfer for urgent campaign settlement,2026-04-25\n"
                    ),
                    "text/csv",
                )
            },
        )

        assert response.status_code == 200
        body = response.json()
        assert body["imported_count"] == 1
        imported_tx = body["transactions"][0]
        assert imported_tx["fraud_risk_level"] == "critical"
        assert imported_tx["fraud_probability"] == 0.88

        insight = db_session.query(AIInsight).filter(AIInsight.user_id == user.user_id).one()
        assert insight.rule_id == "ml_unusual_transaction"
        assert insight.severity == "critical"
        assert insight.metadata_json is not None
        assert insight.metadata_json["transaction_id"] == imported_tx["transaction_id"]

        unusual_log = (
            db_session.query(SystemLog)
            .filter(
                SystemLog.user_id == user.user_id,
                SystemLog.event_type == "unusual_transaction_detected",
            )
            .one()
        )
        assert unusual_log.metadata_json is not None
        assert unusual_log.metadata_json["transaction_id"] == imported_tx["transaction_id"]

        list_response = client.get("/transactions")
        assert list_response.status_code == 200
        assert list_response.json()[0]["fraud_risk_level"] == "critical"
        assert fake_detector.payloads == [
            {
                "amount": 45000.0,
                "type": "CASH_OUT",
                "step": 0,
            }
        ]
    finally:
        app.dependency_overrides.clear()
