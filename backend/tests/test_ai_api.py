from datetime import date, datetime

from fastapi.testclient import TestClient

import app.api.ai as ai_api_module
from app.core.security import create_access_token
from app.db.session import get_db
from app.main import app
from app.models.ai_insight import AIInsight
from app.models.category import Category
from app.models.system_log import SystemLog
from app.models.transaction import Transaction
from app.models.user import User


def _build_authenticated_client(db_session, user: User) -> TestClient:
    app.dependency_overrides[get_db] = lambda: db_session
    client = TestClient(app)
    client.cookies.set("access_token", create_access_token(str(user.user_id)))
    return client


def test_ai_insights_requires_authentication(db_session):
    app.dependency_overrides[get_db] = lambda: db_session
    client = TestClient(app)

    try:
        response = client.get("/ai/insights")
        assert response.status_code == 401
        assert response.json()["detail"] == "Not authenticated"
    finally:
        app.dependency_overrides.clear()


def test_ai_generate_endpoint_uses_custom_period_and_writes_rule_tracked_insights(db_session):
    user = User(name="API Insight User", email="api-insight@example.com", password_hash="x")
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)

    income = Category(user_id=user.user_id, name="Sales", type="income")
    marketing = Category(user_id=user.user_id, name="Marketing", type="expense")
    db_session.add_all([income, marketing])
    db_session.commit()
    db_session.refresh(income)
    db_session.refresh(marketing)

    db_session.add_all(
        [
            Transaction(
                user_id=user.user_id,
                category_id=income.category_id,
                amount=1000.0,
                type="income",
                description="Monthly sales",
                date=date(2026, 4, 5),
            ),
            Transaction(
                user_id=user.user_id,
                category_id=marketing.category_id,
                amount=1200.0,
                type="expense",
                description="Campaign spend",
                date=date(2026, 4, 12),
            ),
        ]
    )
    db_session.commit()

    app.dependency_overrides[get_db] = lambda: db_session
    client = TestClient(app)
    client.cookies.set("access_token", create_access_token(str(user.user_id)))

    try:
        response = client.post(
            "/ai/generate",
            json={"period_start": "2026-04-01", "period_end": "2026-04-30"},
        )
        assert response.status_code == 200
        body = response.json()
        assert len(body) >= 1
        assert {item["period_start"] for item in body} == {"2026-04-01"}
        assert {item["period_end"] for item in body} == {"2026-04-30"}

        stored_insights = db_session.query(AIInsight).filter(AIInsight.user_id == user.user_id).all()
        assert stored_insights
        assert all(insight.rule_id for insight in stored_insights)
        assert any((insight.metadata_json or {}).get("scope_key") for insight in stored_insights)

        logs = db_session.query(SystemLog).filter(SystemLog.user_id == user.user_id).order_by(SystemLog.log_id.asc()).all()
        assert logs[-1].event_type == "generate_insights"
    finally:
        app.dependency_overrides.clear()


def test_ai_generate_endpoint_uses_default_period_when_payload_is_omitted(db_session, monkeypatch):
    class FixedDate(date):
        @classmethod
        def today(cls):
            return cls(2026, 4, 30)

    monkeypatch.setattr(ai_api_module, "date", FixedDate)

    user = User(name="API Default Period User", email="api-default-period@example.com", password_hash="x")
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)

    income = Category(user_id=user.user_id, name="Sales", type="income")
    expense = Category(user_id=user.user_id, name="Operations", type="expense")
    db_session.add_all([income, expense])
    db_session.commit()
    db_session.refresh(income)
    db_session.refresh(expense)

    db_session.add_all(
        [
            Transaction(
                user_id=user.user_id,
                category_id=income.category_id,
                amount=1000.0,
                type="income",
                description="Monthly sales",
                date=date(2026, 4, 5),
            ),
            Transaction(
                user_id=user.user_id,
                category_id=expense.category_id,
                amount=900.0,
                type="expense",
                description="Monthly spend",
                date=date(2026, 4, 12),
            ),
        ]
    )
    db_session.commit()

    client = _build_authenticated_client(db_session, user)

    try:
        response = client.post("/ai/generate")
        assert response.status_code == 200
        body = response.json()
        assert len(body) >= 1
        assert {item["period_start"] for item in body} == {"2026-03-31"}
        assert {item["period_end"] for item in body} == {"2026-04-30"}
    finally:
        app.dependency_overrides.clear()


def test_ai_insight_filters_and_timeseries_route_behaviour(db_session):
    user = User(name="Insight Filter User", email="insight-filter@example.com", password_hash="x")
    other_user = User(name="Other Insight User", email="other-insight@example.com", password_hash="x")
    db_session.add_all([user, other_user])
    db_session.commit()
    db_session.refresh(user)
    db_session.refresh(other_user)

    db_session.add_all(
        [
            AIInsight(
                user_id=user.user_id,
                rule_id="expense_ratio",
                title="March Warning",
                message="March spend is high",
                severity="warning",
                period_start=date(2026, 3, 1),
                period_end=date(2026, 3, 31),
                created_at=datetime(2026, 3, 15, 9, 30, 0),
                metadata_json={"scope_key": "period"},
            ),
            AIInsight(
                user_id=user.user_id,
                rule_id="income_drop_percent",
                title="April Info",
                message="April is on track",
                severity="info",
                period_start=date(2026, 4, 1),
                period_end=date(2026, 4, 30),
                created_at=datetime(2026, 4, 3, 11, 0, 0),
                metadata_json={"scope_key": "period"},
            ),
            AIInsight(
                user_id=other_user.user_id,
                rule_id="expense_ratio",
                title="Other Critical",
                message="Other user issue",
                severity="critical",
                period_start=date(2026, 4, 1),
                period_end=date(2026, 4, 30),
                created_at=datetime(2026, 4, 4, 8, 0, 0),
                metadata_json={"scope_key": "period"},
            ),
        ]
    )
    db_session.commit()

    app.dependency_overrides[get_db] = lambda: db_session
    client = TestClient(app)
    client.cookies.set("access_token", create_access_token(str(user.user_id)))

    try:
        insights_response = client.get("/ai/insights", params={"date_from": "2026-04-01", "severity": "info"})
        assert insights_response.status_code == 200
        insights_body = insights_response.json()
        assert len(insights_body) == 1
        assert insights_body[0]["title"] == "April Info"

        insight_series_response = client.get("/ai/insights/timeseries", params={"granularity": "month"})
        assert insight_series_response.status_code == 200
        assert insight_series_response.json() == [
            {
                "bucket": "2026-03-01",
                "insights_count": 1,
                "info_count": 0,
                "warning_count": 1,
                "critical_count": 0,
            },
            {
                "bucket": "2026-04-01",
                "insights_count": 1,
                "info_count": 1,
                "warning_count": 0,
                "critical_count": 0,
            },
        ]
    finally:
        app.dependency_overrides.clear()


def test_ai_insight_timeseries_supports_day_granularity(db_session):
    user = User(name="Insight Day Series User", email="insight-day-series@example.com", password_hash="x")
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)

    db_session.add_all(
        [
            AIInsight(
                user_id=user.user_id,
                rule_id="expense_ratio",
                title="First Day Warning",
                message="First day warning",
                severity="warning",
                period_start=date(2026, 4, 1),
                period_end=date(2026, 4, 1),
                created_at=datetime(2026, 4, 1, 9, 0, 0),
                metadata_json={"scope_key": "period"},
            ),
            AIInsight(
                user_id=user.user_id,
                rule_id="income_drop_percent",
                title="Second Day Info",
                message="Second day info",
                severity="info",
                period_start=date(2026, 4, 2),
                period_end=date(2026, 4, 2),
                created_at=datetime(2026, 4, 2, 10, 0, 0),
                metadata_json={"scope_key": "period"},
            ),
        ]
    )
    db_session.commit()

    client = _build_authenticated_client(db_session, user)

    try:
        response = client.get("/ai/insights/timeseries", params={"granularity": "day"})
        assert response.status_code == 200
        assert response.json() == [
            {
                "bucket": "2026-04-01",
                "insights_count": 1,
                "info_count": 0,
                "warning_count": 1,
                "critical_count": 0,
            },
            {
                "bucket": "2026-04-02",
                "insights_count": 1,
                "info_count": 1,
                "warning_count": 0,
                "critical_count": 0,
            },
        ]
    finally:
        app.dependency_overrides.clear()


def test_ai_endpoints_return_422_for_invalid_ranges_and_granularity(db_session):
    user = User(name="AI Validation User", email="ai-validation@example.com", password_hash="x")
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)

    client = _build_authenticated_client(db_session, user)

    try:
        generate_response = client.post(
            "/ai/generate",
            json={"period_start": "2026-05-01", "period_end": "2026-04-01"},
        )
        assert generate_response.status_code == 422

        insights_response = client.get(
            "/ai/insights",
            params={"date_from": "2026-05-01", "date_to": "2026-04-01"},
        )
        assert insights_response.status_code == 422

        timeseries_range_response = client.get(
            "/ai/insights/timeseries",
            params={"date_from": "2026-05-01", "date_to": "2026-04-01"},
        )
        assert timeseries_range_response.status_code == 422

        timeseries_granularity_response = client.get(
            "/ai/insights/timeseries",
            params={"granularity": "year"},
        )
        assert timeseries_granularity_response.status_code == 422
    finally:
        app.dependency_overrides.clear()
