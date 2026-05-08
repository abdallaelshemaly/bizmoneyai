from datetime import date

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401
from app.api.dashboard import router as dashboard_router
from app.core.security import create_access_token
from app.core.time import utcnow
from app.db.session import Base, get_db
from app.models.budget import Budget
from app.models.category import Category
from app.models.transaction import Transaction
from app.models.user import User


def test_dashboard_summary_populates_charts_ratios_and_budgets():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    db = TestingSessionLocal()

    app = FastAPI()
    app.include_router(dashboard_router)

    def override_get_db():
        try:
            yield db
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db

    current_month = utcnow().date().replace(day=1)
    tx_date = date(current_month.year, current_month.month, min(6, current_month.day or 1))
    user = User(name="Dashboard User", email="dashboard@example.com", password_hash="pw")
    db.add(user)
    db.commit()
    db.refresh(user)

    salary = Category(user_id=user.user_id, name="Salary", type="income")
    marketing = Category(user_id=user.user_id, name="Marketing", type="expense")
    rent = Category(user_id=user.user_id, name="Rent", type="expense")
    db.add_all([salary, marketing, rent])
    db.commit()
    db.refresh(salary)
    db.refresh(marketing)
    db.refresh(rent)

    db.add_all(
        [
            Transaction(user_id=user.user_id, category_id=salary.category_id, amount=3100.0, type="INCOME", date=tx_date),
            Transaction(user_id=user.user_id, category_id=marketing.category_id, amount=1750.0, type="EXPENSE", date=tx_date),
            Transaction(user_id=user.user_id, category_id=rent.category_id, amount=700.0, type="expense", date=tx_date),
            Budget(user_id=user.user_id, category_id=marketing.category_id, amount=1000.0, month=current_month),
            Budget(user_id=user.user_id, category_id=rent.category_id, amount=750.0, month=current_month),
        ]
    )
    db.commit()

    client = TestClient(app)
    client.cookies.set("access_token", create_access_token(str(user.user_id)))

    try:
        response = client.get("/dashboard/summary")
        assert response.status_code == 200
        body = response.json()

        assert body["total_income"] == 3100.0
        assert body["total_expense"] == 2450.0
        assert body["balance"] == 650.0
        assert body["transaction_count"] == 3
        assert body["expense_ratio"] == 2450.0 / 3100.0
        assert body["savings_rate"] == 650.0 / 3100.0
        assert body["monthly_average_income"] == 3100.0
        assert body["monthly_average_expense"] == 2450.0
        assert body["top_expense_category_name"] == "Marketing"
        assert body["top_expense_category_total"] == 1750.0
        assert body["category_breakdown"] == [
            {"category_name": "Marketing", "total": 1750.0},
            {"category_name": "Rent", "total": 700.0},
        ]
        assert body["monthly_trend"][-1] == {
            "month": current_month.strftime("%Y-%m"),
            "income": 3100.0,
            "expense": 2450.0,
        }
        assert body["budget_total"] == 1750.0
        assert body["budget_spent"] == 2450.0
        assert body["budget_remaining"] == -700.0
        assert body["over_budget_count"] == 1
        assert body["budget_month"] == current_month.strftime("%Y-%m")
        assert body["health_status"] == "at_risk"
    finally:
        app.dependency_overrides.clear()
        db.close()
        Base.metadata.drop_all(bind=engine)


def test_dashboard_summary_uses_selected_budget_month():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    db = TestingSessionLocal()

    app = FastAPI()
    app.include_router(dashboard_router)

    def override_get_db():
        try:
            yield db
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db

    user = User(name="Dashboard Month User", email="dashboard-month@example.com", password_hash="pw")
    db.add(user)
    db.commit()
    db.refresh(user)

    marketing = Category(user_id=user.user_id, name="Marketing", type="expense")
    db.add(marketing)
    db.commit()
    db.refresh(marketing)

    db.add_all(
        [
            Transaction(
                user_id=user.user_id,
                category_id=marketing.category_id,
                amount=48999.0,
                type="expense",
                date=date(2026, 4, 25),
            ),
            Budget(
                user_id=user.user_id,
                category_id=marketing.category_id,
                amount=4000.0,
                month=date(2026, 4, 1),
            ),
        ]
    )
    db.commit()

    client = TestClient(app)
    client.cookies.set("access_token", create_access_token(str(user.user_id)))

    try:
        response = client.get("/dashboard/summary", params={"month": "2026-04-01"})
        assert response.status_code == 200
        body = response.json()
        assert body["budget_month"] == "2026-04"
        assert body["budget_total"] == 4000.0
        assert body["budget_spent"] == 48999.0
        assert body["budget_remaining"] == -44999.0
        assert body["over_budget_count"] == 1
    finally:
        app.dependency_overrides.clear()
        db.close()
        Base.metadata.drop_all(bind=engine)
