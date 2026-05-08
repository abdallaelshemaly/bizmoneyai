from datetime import date, datetime

from fastapi import FastAPI
from fastapi.testclient import TestClient

import app.api.admin_auth as admin_auth_module
import app.api.ai as ai_module
import app.api.auth as auth_module
import app.services.admin_analytics as admin_analytics_module
from app.api.admin import router as admin_router
from app.api.admin_auth import protected_router as admin_protected_router
from app.api.admin_auth import router as admin_auth_router
from app.api.ai import router as ai_router
from app.api.auth import router as auth_router
from app.api.budgets import router as budgets_router
from app.api.categories import router as categories_router
from app.api.transactions import router as transactions_router
from app.core.security import create_access_token
from app.db.session import get_db
from app.models.admin import Admin
from app.models.ai_insight import AIInsight
from app.models.budget import Budget
from app.models.category import Category
from app.models.system_log import SystemLog
from app.models.transaction import Transaction
from app.models.user import User


def create_test_app() -> FastAPI:
    app = FastAPI()
    app.include_router(admin_auth_router)
    app.include_router(admin_protected_router)
    app.include_router(admin_router)
    app.include_router(auth_router)
    app.include_router(categories_router)
    app.include_router(transactions_router)
    app.include_router(budgets_router)
    app.include_router(ai_router)
    return app


def test_admin_read_endpoints_return_analytics(db_session, monkeypatch):
    monkeypatch.setattr(admin_auth_module, "verify_password", lambda plain, hashed: plain == hashed)
    monkeypatch.setattr(admin_analytics_module, "utcnow", lambda: datetime(2026, 4, 15, 12, 0, 0))

    admin = Admin(name="Ops Admin", email="admin@example.com", password_hash="secret123")
    user_one = User(name="Alpha User", email="alpha@example.com", password_hash="pw", is_active=True)
    user_two = User(name="Beta User", email="beta@example.com", password_hash="pw", is_active=True)
    db_session.add_all([admin, user_one, user_two])
    db_session.commit()
    db_session.refresh(user_one)
    db_session.refresh(user_two)

    food = Category(user_id=user_one.user_id, name="Food", type="expense")
    travel = Category(user_id=user_two.user_id, name="Travel", type="expense")
    db_session.add_all([food, travel])
    db_session.commit()
    db_session.refresh(food)
    db_session.refresh(travel)

    tx = Transaction(
        user_id=user_one.user_id,
        category_id=food.category_id,
        amount=80.0,
        type="expense",
        description="Team lunch",
        date=date(2026, 4, 3),
    )
    secondary_tx = Transaction(
        user_id=user_two.user_id,
        category_id=travel.category_id,
        amount=20.0,
        type="expense",
        description="Client commute",
        date=date(2026, 4, 4),
    )
    bonus_tx = Transaction(
        user_id=user_one.user_id,
        category_id=food.category_id,
        amount=30.0,
        type="income",
        description="Vendor refund",
        date=date(2026, 4, 5),
    )
    budget = Budget(
        user_id=user_one.user_id,
        category_id=food.category_id,
        amount=50.0,
        month=date(2026, 4, 1),
        note="April food",
    )
    secondary_budget = Budget(
        user_id=user_two.user_id,
        category_id=travel.category_id,
        amount=100.0,
        month=date(2026, 4, 1),
        note="April travel",
    )
    insight = AIInsight(
        user_id=user_one.user_id,
        title="Expense Spike",
        message="Food spending spiked.",
        severity="warning",
        period_start=date(2026, 4, 1),
        period_end=date(2026, 4, 30),
    )
    secondary_insight = AIInsight(
        user_id=user_two.user_id,
        title="Travel Watch",
        message="Travel spending is elevated.",
        severity="info",
        period_start=date(2026, 4, 1),
        period_end=date(2026, 4, 30),
    )
    unusual_insight = AIInsight(
        user_id=user_one.user_id,
        rule_id="ml_unusual_transaction",
        title="Critical Unusual Transaction Detected",
        message="Critical unusual transaction detected. Review this transaction immediately.",
        severity="critical",
        period_start=date(2026, 4, 3),
        period_end=date(2026, 4, 3),
        metadata_json={
            "scope_key": "transaction:1",
            "transaction_id": 1,
            "risk_level": "critical",
            "fraud_probability": 0.91,
        },
    )
    user_log = SystemLog(
        user_id=user_one.user_id,
        event_type="user_login",
        message="Alpha User logged in",
        level="info",
    )
    for record in (
        admin,
        user_one,
        user_two,
        food,
        travel,
        tx,
        secondary_tx,
        bonus_tx,
        budget,
        secondary_budget,
        insight,
        secondary_insight,
        unusual_insight,
        user_log,
    ):
        record.created_at = datetime(2026, 4, 5, 12, 0, 0)
    db_session.add_all([tx, secondary_tx, bonus_tx, budget, secondary_budget, insight, secondary_insight, unusual_insight, user_log])
    db_session.commit()

    app = create_test_app()
    app.dependency_overrides[get_db] = lambda: db_session
    client = TestClient(app)

    try:
        login_response = client.post(
            "/admin/auth/login",
            json={"email": "admin@example.com", "password": "secret123"},
        )
        assert login_response.status_code == 200

        dashboard = client.get("/admin/dashboard")
        assert dashboard.status_code == 200
        dashboard_body = dashboard.json()
        assert dashboard_body["total_users"] == 2
        assert dashboard_body["total_transactions"] == 3
        assert dashboard_body["total_categories"] == 2
        assert dashboard_body["total_budgets"] == 2
        assert dashboard_body["total_ai_insights"] == 3
        assert dashboard_body["total_unusual_transactions"] == 1
        assert dashboard_body["unusual_warning_count"] == 0
        assert dashboard_body["unusual_critical_count"] == 1
        assert dashboard_body["recent_unusual_transaction_insights"][0]["severity"] == "critical"
        assert dashboard_body["recent_unusual_transaction_insights"][0]["transaction_id"] == 1
        assert dashboard_body["recent_unusual_transaction_insights"][0]["fraud_probability"] == 0.91
        assert any(item["total_events"] >= 1 for item in dashboard_body["activity_trends"])
        assert any(item["transactions_count"] == 1 for item in dashboard_body["transaction_trends"])
        assert any(item["total_amount"] == 80.0 for item in dashboard_body["transaction_trends"])
        assert {item["label"] for item in dashboard_body["insight_severity_distribution"]} == {"critical", "info", "warning"}
        assert dashboard_body["spend_distribution"][0]["category_name"] == "Food"
        assert dashboard_body["top_overspending_categories"][0]["category_name"] == "Food"
        assert dashboard_body["over_budget_categories"] == 1
        assert dashboard_body["total_overspending_amount"] == 30.0
        assert dashboard_body["most_active_users"][0]["email"] == "alpha@example.com"
        assert dashboard_body["recent_logs"][0]["event_type"] == "admin_login"

        overview_response = client.get("/admin/analytics/overview")
        assert overview_response.status_code == 200
        overview_body = overview_response.json()
        assert overview_body["total_users"] == 2
        assert overview_body["total_transactions"] == 3
        assert overview_body["recent_logs"][0]["event_type"] == "admin_login"

        transactions_analytics_response = client.get("/admin/analytics/transactions")
        assert transactions_analytics_response.status_code == 200
        transactions_analytics_body = transactions_analytics_response.json()
        assert any(item["transactions_count"] == 1 for item in transactions_analytics_body["transaction_trends"])
        assert transactions_analytics_body["spend_distribution"][0]["category_name"] == "Food"

        users_analytics_response = client.get("/admin/analytics/users")
        assert users_analytics_response.status_code == 200
        assert users_analytics_response.json()["most_active_users"][0]["email"] == "alpha@example.com"

        insights_analytics_response = client.get("/admin/analytics/insights")
        assert insights_analytics_response.status_code == 200
        insights_analytics_body = insights_analytics_response.json()
        assert {item["label"] for item in insights_analytics_body["insight_severity_distribution"]} == {"critical", "info", "warning"}
        assert insights_analytics_body["total_unusual_transactions"] == 1
        assert insights_analytics_body["unusual_warning_count"] == 0
        assert insights_analytics_body["unusual_critical_count"] == 1
        assert insights_analytics_body["recent_unusual_transaction_insights"][0]["title"] == "Critical Unusual Transaction Detected"

        budgets_analytics_response = client.get("/admin/analytics/budgets")
        assert budgets_analytics_response.status_code == 200
        budgets_analytics_body = budgets_analytics_response.json()
        assert budgets_analytics_body["top_overspending_categories"][0]["category_name"] == "Food"
        assert budgets_analytics_body["over_budget_categories"] == 1
        assert budgets_analytics_body["total_overspending_amount"] == 30.0

        scoped_dashboard = client.get("/admin/dashboard", params={"user_id": user_one.user_id})
        assert scoped_dashboard.status_code == 200
        scoped_dashboard_body = scoped_dashboard.json()
        assert scoped_dashboard_body["total_users"] == 1
        assert scoped_dashboard_body["total_transactions"] == 2
        assert scoped_dashboard_body["total_categories"] == 1
        assert scoped_dashboard_body["total_budgets"] == 1
        assert scoped_dashboard_body["total_ai_insights"] == 2
        assert scoped_dashboard_body["total_unusual_transactions"] == 1
        assert scoped_dashboard_body["unusual_warning_count"] == 0
        assert scoped_dashboard_body["unusual_critical_count"] == 1
        assert scoped_dashboard_body["insight_severity_distribution"] == [
            {"label": "critical", "count": 1},
            {"label": "warning", "count": 1},
        ]
        assert scoped_dashboard_body["spend_distribution"] == [
            {"category_name": "Food", "total_amount": 80.0, "transactions_count": 1}
        ]
        assert scoped_dashboard_body["top_overspending_categories"] == [
            {"category_name": "Food", "over_budget_count": 1, "total_overspent": 30.0}
        ]
        assert scoped_dashboard_body["over_budget_categories"] == 1
        assert scoped_dashboard_body["total_overspending_amount"] == 30.0
        assert len(scoped_dashboard_body["most_active_users"]) == 1
        assert scoped_dashboard_body["most_active_users"][0]["email"] == "alpha@example.com"
        assert scoped_dashboard_body["recent_logs"][0]["event_type"] == "user_login"
        assert scoped_dashboard_body["recent_logs"][0]["user_email"] == "alpha@example.com"

        scoped_transactions_analytics = client.get("/admin/analytics/transactions", params={"user_id": user_one.user_id})
        assert scoped_transactions_analytics.status_code == 200
        assert scoped_transactions_analytics.json()["spend_distribution"] == [
            {"category_name": "Food", "total_amount": 80.0, "transactions_count": 1}
        ]

        scoped_users_analytics = client.get("/admin/analytics/users", params={"user_id": user_one.user_id})
        assert scoped_users_analytics.status_code == 200
        assert len(scoped_users_analytics.json()["most_active_users"]) == 1

        missing_dashboard = client.get("/admin/dashboard", params={"user_id": 999999})
        assert missing_dashboard.status_code == 404

        missing_overview = client.get("/admin/analytics/overview", params={"user_id": 999999})
        assert missing_overview.status_code == 404

        users_response = client.get("/admin/users", params={"search": "alpha"})
        assert users_response.status_code == 200
        users_body = users_response.json()
        assert users_body["total"] == 1
        assert users_body["limit"] == 10
        assert users_body["offset"] == 0
        assert users_body["users"][0]["transactions_count"] == 2
        assert users_body["users"][0]["categories_count"] == 1
        assert users_body["users"][0]["budgets_count"] == 1
        assert users_body["users"][0]["insights_count"] == 2
        assert users_body["users"][0]["last_activity"] is not None
        assert users_body["summary"]["active_count"] == 1

        paged_users_response = client.get(
            "/admin/users",
            params={"limit": 1, "offset": 1, "sort_by": "name", "sort_order": "asc"},
        )
        assert paged_users_response.status_code == 200
        paged_users_body = paged_users_response.json()
        assert paged_users_body["total"] == 2
        assert paged_users_body["limit"] == 1
        assert paged_users_body["offset"] == 1
        assert paged_users_body["users"][0]["email"] == "beta@example.com"

        transactions_response = client.get(
            "/admin/transactions",
            params={"user_id": user_one.user_id, "type": "expense"},
        )
        assert transactions_response.status_code == 200
        transactions_body = transactions_response.json()
        assert transactions_body["total"] == 1
        assert transactions_body["summary"]["expense_count"] == 1
        assert transactions_body["transactions"][0]["category_name"] == "Food"

        categories_response = client.get("/admin/categories", params={"search": "food", "type": "expense"})
        assert categories_response.status_code == 200
        categories_body = categories_response.json()
        assert categories_body["total"] == 1
        assert categories_body["summary"]["expense_count"] == 1
        assert categories_body["categories"][0]["transactions_count"] == 2
        assert categories_body["categories"][0]["budgets_count"] == 1

        budgets_response = client.get("/admin/budgets")
        assert budgets_response.status_code == 200
        budgets_body = budgets_response.json()
        assert budgets_body["total"] == 2
        assert budgets_body["overspending_analysis"]["over_budget_count"] == 1
        assert budgets_body["overspending_analysis"]["total_overspent"] == 30.0
        assert budgets_body["popular_categories"][0]["category_name"] == "Food"
        assert budgets_body["budget_trends"][0]["month"] == "2026-04"

        scoped_budgets_response = client.get("/admin/budgets", params={"user_id": user_two.user_id})
        assert scoped_budgets_response.status_code == 200
        scoped_budgets_body = scoped_budgets_response.json()
        assert len(scoped_budgets_body["budgets"]) == 1
        assert scoped_budgets_body["budgets"][0]["category_name"] == "Travel"
        assert scoped_budgets_body["overspending_analysis"]["total_spent"] == 20.0

        insights_response = client.get(
            "/admin/insights",
            params={"severity": "warning", "date_from": "2026-04-01", "date_to": "2026-04-30"},
        )
        assert insights_response.status_code == 200
        insights_body = insights_response.json()
        assert insights_body["total"] == 1
        assert insights_body["insights"][0]["title"] == "Expense Spike"
        assert insights_body["severity_distribution"][0] == {"label": "warning", "count": 1}
        assert insights_body["trigger_frequency"][0] == {"label": "Expense Spike", "count": 1}

        logs_response = client.get("/admin/logs", params={"event_type": "admin_login"})
        assert logs_response.status_code == 200
        logs_body = logs_response.json()
        assert logs_body["total"] == 1
        assert logs_body["logs"][0]["admin_email"] == "admin@example.com"
        assert logs_body["logs"][0]["metadata"] == {
            "user_id": None,
            "admin_id": admin.admin_id,
            "entity_id": admin.admin_id,
            "admin_email": "admin@example.com",
        }
    finally:
        app.dependency_overrides.clear()


def test_admin_mutations_update_state_and_write_logs(db_session, monkeypatch):
    monkeypatch.setattr(admin_auth_module, "verify_password", lambda plain, hashed: plain == hashed)
    monkeypatch.setattr(auth_module, "verify_password", lambda plain, hashed: plain == hashed)

    admin = Admin(name="Ops Admin", email="admin@example.com", password_hash="secret123")
    user = User(name="Managed User", email="managed@example.com", password_hash="pw", is_active=True)
    db_session.add_all([admin, user])
    db_session.commit()
    db_session.refresh(user)

    removable_category = Category(user_id=user.user_id, name="Spam", type="expense")
    existing_category = Category(user_id=user.user_id, name="Sales", type="income")
    db_session.add_all([removable_category, existing_category])
    db_session.commit()
    db_session.refresh(removable_category)

    app = create_test_app()
    app.dependency_overrides[get_db] = lambda: db_session
    client = TestClient(app)

    try:
        login_response = client.post(
            "/admin/auth/login",
            json={"email": "admin@example.com", "password": "secret123"},
        )
        assert login_response.status_code == 200

        status_response = client.patch(
            f"/admin/users/{user.user_id}/status",
            json={"is_active": False},
        )
        assert status_response.status_code == 200
        assert status_response.json()["is_active"] is False

        blocked_login_response = client.post(
            "/auth/login",
            json={"email": "managed@example.com", "password": "pw"},
        )
        assert blocked_login_response.status_code == 403

        defaults_response = client.post(
            "/admin/categories/defaults",
            params={"user_id": user.user_id},
        )
        assert defaults_response.status_code == 200
        assert defaults_response.json()["created_count"] >= 1

        delete_category_response = client.delete(f"/admin/categories/{removable_category.category_id}")
        assert delete_category_response.status_code == 204
        assert db_session.query(Category).filter(Category.category_id == removable_category.category_id).first() is None

        delete_user_response = client.delete(f"/admin/users/{user.user_id}")
        assert delete_user_response.status_code == 204
        assert db_session.query(User).filter(User.user_id == user.user_id).first() is None

        event_types = [item.event_type for item in db_session.query(SystemLog).order_by(SystemLog.log_id.asc()).all()]
        assert "admin_login" in event_types
        assert "disable_user" in event_types
        assert "create_category" in event_types
        assert "delete_category" in event_types
        assert "delete_user" in event_types

        status_log = db_session.query(SystemLog).filter(SystemLog.event_type == "disable_user").one()
        assert status_log.metadata_json == {
            "user_id": user.user_id,
            "admin_id": admin.admin_id,
            "entity_id": user.user_id,
            "email": "managed@example.com",
            "is_active": False,
        }
    finally:
        app.dependency_overrides.clear()


def test_admin_routes_require_admin_authentication(db_session):
    admin = Admin(name="Ops Admin", email="admin@example.com", password_hash="secret123")
    user = User(name="Regular User", email="user@example.com", password_hash="pw", is_active=True)
    db_session.add_all([admin, user])
    db_session.commit()
    db_session.refresh(user)

    app = create_test_app()
    app.dependency_overrides[get_db] = lambda: db_session
    client = TestClient(app)

    protected_paths = [
        ("get", "/admin/dashboard"),
        ("get", "/admin/analytics/overview"),
        ("get", "/admin/users"),
        ("get", "/admin/auth/me"),
        ("post", "/admin/auth/logout"),
    ]

    try:
        for method, path in protected_paths:
            response = getattr(client, method)(path)
            assert response.status_code == 401

        client.cookies.set("access_token", create_access_token(str(user.user_id)))

        for method, path in protected_paths:
            response = getattr(client, method)(path)
            assert response.status_code == 403
            assert response.json()["detail"] == "Admin access required"
    finally:
        app.dependency_overrides.clear()


def test_auth_and_ai_routes_write_requested_system_logs(db_session, monkeypatch):
    monkeypatch.setattr(auth_module, "get_password_hash", lambda password: password)
    monkeypatch.setattr(auth_module, "verify_password", lambda plain, hashed: plain == hashed)

    def fake_run_rules_for_user(db, user_id, period_start, period_end):
        insight = AIInsight(
            user_id=user_id,
            title="Synthetic Insight",
            message="Generated by test",
            severity="info",
            period_start=period_start,
            period_end=period_end,
        )
        db.add(insight)
        db.commit()
        db.refresh(insight)
        return [insight]

    monkeypatch.setattr(ai_module, "run_rules_for_user", fake_run_rules_for_user)

    app = create_test_app()
    app.dependency_overrides[get_db] = lambda: db_session
    client = TestClient(app)

    try:
        register_response = client.post(
            "/auth/register",
            json={"name": "Log User", "email": "log-user@example.com", "password": "pw1234"},
        )
        assert register_response.status_code == 201

        login_response = client.post(
            "/auth/login",
            json={"email": "log-user@example.com", "password": "pw1234"},
        )
        assert login_response.status_code == 200
        set_cookie = login_response.headers.get("set-cookie", "").lower()
        assert "access_token=" in set_cookie
        assert "httponly" in set_cookie

        me_response = client.get("/auth/me")
        assert me_response.status_code == 200
        assert me_response.json()["email"] == "log-user@example.com"
        assert me_response.json()["is_active"] is True

        generate_response = client.post("/ai/generate", json={})
        assert generate_response.status_code == 200
        assert generate_response.json()[0]["title"] == "Synthetic Insight"

        event_types = [item.event_type for item in db_session.query(SystemLog).order_by(SystemLog.log_id.asc()).all()]
        assert "user_registration" in event_types
        assert "user_login" in event_types
        assert "generate_insights" in event_types
    finally:
        app.dependency_overrides.clear()


def test_admin_dashboard_cache_refreshes_after_user_and_admin_mutations(db_session, monkeypatch):
    monkeypatch.setattr(admin_auth_module, "verify_password", lambda plain, hashed: plain == hashed)

    def fake_run_rules_for_user(db, user_id, period_start, period_end):
        insight = AIInsight(
            user_id=user_id,
            title="Synthetic Insight",
            message="Generated by test",
            severity="warning",
            period_start=period_start,
            period_end=period_end,
        )
        db.add(insight)
        db.commit()
        db.refresh(insight)
        return [insight]

    monkeypatch.setattr(ai_module, "run_rules_for_user", fake_run_rules_for_user)

    admin = Admin(name="Ops Admin", email="admin@example.com", password_hash="secret123")
    user = User(name="Cache User", email="cache-user@example.com", password_hash="pw", is_active=True)
    db_session.add_all([admin, user])
    db_session.commit()
    db_session.refresh(user)

    app = create_test_app()
    app.dependency_overrides[get_db] = lambda: db_session
    client = TestClient(app)

    try:
        login_response = client.post(
            "/admin/auth/login",
            json={"email": "admin@example.com", "password": "secret123"},
        )
        assert login_response.status_code == 200

        initial_dashboard = client.get("/admin/dashboard")
        assert initial_dashboard.status_code == 200
        assert initial_dashboard.json()["total_users"] == 1
        assert initial_dashboard.json()["total_categories"] == 0
        assert initial_dashboard.json()["total_transactions"] == 0
        assert initial_dashboard.json()["total_budgets"] == 0
        assert initial_dashboard.json()["total_ai_insights"] == 0

        client.cookies.set("access_token", create_access_token(str(user.user_id)))

        category_response = client.post(
            "/categories",
            json={"name": "Travel", "type": "expense"},
        )
        assert category_response.status_code == 201
        category_id = category_response.json()["category_id"]

        category_dashboard = client.get("/admin/dashboard")
        assert category_dashboard.status_code == 200
        assert category_dashboard.json()["total_categories"] == 1
        assert category_dashboard.json()["recent_logs"][0]["event_type"] == "create_category"

        transaction_response = client.post(
            "/transactions",
            json={
                "category_id": category_id,
                "amount": 120.5,
                "type": "expense",
                "description": "Conference travel",
                "date": "2026-04-14",
            },
        )
        assert transaction_response.status_code == 201

        transaction_dashboard = client.get("/admin/dashboard")
        assert transaction_dashboard.status_code == 200
        assert transaction_dashboard.json()["total_transactions"] == 1
        assert transaction_dashboard.json()["recent_logs"][0]["event_type"] == "create_transaction"

        budget_response = client.post(
            "/budgets",
            json={
                "category_id": category_id,
                "amount": 200,
                "month": "2026-04-01",
                "note": "Travel budget",
            },
        )
        assert budget_response.status_code == 201

        budget_dashboard = client.get("/admin/dashboard")
        assert budget_dashboard.status_code == 200
        assert budget_dashboard.json()["total_budgets"] == 1
        assert budget_dashboard.json()["recent_logs"][0]["event_type"] == "create_budget"

        insight_response = client.post("/ai/generate", json={})
        assert insight_response.status_code == 200

        insight_dashboard = client.get("/admin/dashboard")
        assert insight_dashboard.status_code == 200
        assert insight_dashboard.json()["total_ai_insights"] == 1
        assert insight_dashboard.json()["recent_logs"][0]["event_type"] == "generate_insights"

        disable_response = client.patch(
            f"/admin/users/{user.user_id}/status",
            json={"is_active": False},
        )
        assert disable_response.status_code == 200

        disabled_dashboard = client.get("/admin/dashboard")
        assert disabled_dashboard.status_code == 200
        assert disabled_dashboard.json()["recent_logs"][0]["event_type"] == "disable_user"

        delete_response = client.delete(f"/admin/users/{user.user_id}")
        assert delete_response.status_code == 204

        final_dashboard = client.get("/admin/dashboard")
        assert final_dashboard.status_code == 200
        assert final_dashboard.json()["total_users"] == 0
        assert final_dashboard.json()["total_categories"] == 0
        assert final_dashboard.json()["total_transactions"] == 0
        assert final_dashboard.json()["total_budgets"] == 0
        assert final_dashboard.json()["total_ai_insights"] == 0
        assert final_dashboard.json()["recent_logs"][0]["event_type"] == "delete_user"
    finally:
        app.dependency_overrides.clear()
