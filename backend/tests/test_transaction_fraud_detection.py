from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import app.api.transactions as transactions_api
from app.core.security import create_access_token
from app.db.session import get_db
from app.main import app
from app.models.ai_insight import AIInsight
from app.models.budget import Budget
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


class AmountRoutingFraudDetector:
    def __init__(self, responses_by_amount: dict[float, dict]) -> None:
        self.responses_by_amount = responses_by_amount
        self.payloads: list[dict] = []

    def is_ready(self) -> bool:
        return True

    def predict(self, payload: dict) -> dict:
        self.payloads.append(payload)
        amount = float(payload["amount"])
        return self.responses_by_amount.get(
            amount,
            {
                "is_unusual": False,
                "fraud_probability": 0.0,
                "risk_level": "normal",
                "model_name": "Fake Fraud Detector",
            },
        )


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
        assert unusual_log.level == ("error" if risk_level == "critical" else "warning")
        assert len(fake_detector.payloads) == 1
        detector_payload = fake_detector.payloads[0]
        assert detector_payload["amount"] == 5000.0
        assert detector_payload["type"] == "expense"
        assert detector_payload["category_name"] == "Operations"
        assert detector_payload["date"] == "2026-04-10"
        assert detector_payload["budget_amount"] == 0.0
        assert detector_payload["budget_spent_before"] == 0.0

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
                        "category_id,amount,type,description,date,budget_amount,budget_month\n"
                        f"{category.category_id},45000,expense,Emergency vendor transfer for urgent campaign settlement,2026-04-25,4000,2026-04\n"
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
        assert unusual_log.level == "error"

        list_response = client.get("/transactions")
        assert list_response.status_code == 200
        assert list_response.json()[0]["fraud_risk_level"] == "critical"
        assert len(fake_detector.payloads) == 1
        detector_payload = fake_detector.payloads[0]
        assert detector_payload["amount"] == 45000.0
        assert detector_payload["type"] == "expense"
        assert detector_payload["category_name"] == "Operations"
        assert detector_payload["budget_amount"] == 4000.0
        assert detector_payload["budget_month"] == "2026-04-01"
        assert detector_payload["budget_spent_before"] == 0.0

        budget = db_session.query(Budget).filter(Budget.user_id == user.user_id).one()
        assert budget.amount == 4000.0
    finally:
        app.dependency_overrides.clear()


def test_import_exact_csv_creates_expected_warning_and_critical_insights(db_session, monkeypatch):
    monkeypatch.setattr(
        transactions_api,
        "fraud_detector",
        AmountRoutingFraudDetector(
            {
                45000.0: {
                    "is_unusual": True,
                    "fraud_probability": 0.92,
                    "risk_level": "critical",
                    "model_name": "Fake Fraud Detector",
                },
                16000.0: {
                    "is_unusual": True,
                    "fraud_probability": 0.741667,
                    "risk_level": "warning",
                    "model_name": "Fake Fraud Detector",
                },
                85000.0: {
                    "is_unusual": True,
                    "fraud_probability": 0.92,
                    "risk_level": "critical",
                    "model_name": "Fake Fraud Detector",
                },
            }
        ),
    )
    client, user, _category = _client_with_expense_category(db_session)

    try:
        csv_content = (
            "category_name,amount,type,description,date,budget_amount,budget_month\n"
            "Office Supplies,180,expense,Printer paper and desk supplies,2026-04-03,1500,2026-04\n"
            "Software,850,expense,Team subscription renewal,2026-04-04,4500,2026-04\n"
            "Marketing,900,expense,Campaign spend,2026-04-05,4000,2026-04\n"
            "Travel,620,expense,Regional client visit,2026-04-08,2500,2026-04\n"
            "Sales,7200,income,Client invoice payment,2026-04-10,,\n"
            "Marketing,45000,expense,Emergency vendor transfer for urgent campaign settlement,2026-04-25,4000,2026-04\n"
            "Software,16000,expense,Manual override wire payment for immediate supplier settlement,2026-04-26,4500,2026-04\n"
            "Consulting,85000,expense,Urgent offshore contractor transfer,2026-04-27,9000,2026-04\n"
        )
        response = client.post(
            "/transactions/import-csv",
            files={"file": ("transactions.csv", csv_content, "text/csv")},
        )

        assert response.status_code == 200
        body = response.json()
        assert body["imported_count"] == 8

        suspicious_by_amount = {
            float(tx["amount"]): tx
            for tx in body["transactions"]
            if float(tx["amount"]) in {45000.0, 16000.0, 85000.0}
        }
        assert suspicious_by_amount[45000.0]["fraud_risk_level"] == "critical"
        assert suspicious_by_amount[45000.0]["fraud_probability"] == 0.92
        assert suspicious_by_amount[16000.0]["fraud_risk_level"] == "warning"
        assert suspicious_by_amount[16000.0]["fraud_probability"] == 0.741667
        assert suspicious_by_amount[85000.0]["fraud_risk_level"] == "critical"
        assert suspicious_by_amount[85000.0]["fraud_probability"] == 0.92

        insights = (
            db_session.query(AIInsight)
            .filter(AIInsight.user_id == user.user_id, AIInsight.rule_id == "ml_unusual_transaction")
            .order_by(AIInsight.insight_id.asc())
            .all()
        )
        assert len(insights) == 3
        by_transaction_id = {(insight.metadata_json or {})["transaction_id"]: insight for insight in insights}

        tx_response_by_id = {int(tx["transaction_id"]): tx for tx in body["transactions"]}
        marketing_tx_id = int(suspicious_by_amount[45000.0]["transaction_id"])
        software_tx_id = int(suspicious_by_amount[16000.0]["transaction_id"])
        consulting_tx_id = int(suspicious_by_amount[85000.0]["transaction_id"])

        assert by_transaction_id[marketing_tx_id].severity == "critical"
        assert by_transaction_id[software_tx_id].severity == "warning"
        assert by_transaction_id[consulting_tx_id].severity == "critical"

        logs = (
            db_session.query(SystemLog)
            .filter(SystemLog.user_id == user.user_id, SystemLog.event_type == "unusual_transaction_detected")
            .order_by(SystemLog.log_id.asc())
            .all()
        )
        assert len(logs) == 3
        log_by_tx_id = {log.metadata_json["transaction_id"]: log for log in logs if log.metadata_json is not None}
        assert log_by_tx_id[marketing_tx_id].level == "error"
        assert log_by_tx_id[software_tx_id].level == "warning"
        assert log_by_tx_id[consulting_tx_id].level == "error"

        list_response = client.get("/transactions")
        assert list_response.status_code == 200
        list_by_amount = {float(tx["amount"]): tx for tx in list_response.json() if float(tx["amount"]) in suspicious_by_amount}
        assert list_by_amount[45000.0]["fraud_risk_level"] == "critical"
        assert list_by_amount[16000.0]["fraud_risk_level"] == "warning"
        assert list_by_amount[85000.0]["fraud_risk_level"] == "critical"
        assert list_by_amount[45000.0]["fraud_insight_id"] == by_transaction_id[marketing_tx_id].insight_id
        assert list_by_amount[16000.0]["fraud_insight_id"] == by_transaction_id[software_tx_id].insight_id
        assert list_by_amount[85000.0]["fraud_insight_id"] == by_transaction_id[consulting_tx_id].insight_id
    finally:
        app.dependency_overrides.clear()
