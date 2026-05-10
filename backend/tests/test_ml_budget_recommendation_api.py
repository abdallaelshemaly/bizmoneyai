from __future__ import annotations

from fastapi.testclient import TestClient

import app.api.budgets as budgets_api
from app.core.security import create_access_token
from app.db.session import get_db
from app.main import app
from app.models.budget import Budget
from app.models.category import Category
from app.models.user import User


class FakeBudgetRecommender:
    def __init__(self, response: list[dict]):
        self.response = response
        self.calls: list[int] = []

    def recommend_budgets_for_user(self, db, user: User) -> list[dict]:
        self.calls.append(user.user_id)
        return self.response


def _create_user(db_session) -> User:
    user = User(name="Budget API Rec", email="budget-api-rec@example.com", password_hash="x")
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


def _client(db_session, user: User | None = None) -> TestClient:
    app.dependency_overrides[get_db] = lambda: db_session
    client = TestClient(app)
    if user is not None:
        client.cookies.set("access_token", create_access_token(str(user.user_id)))
    return client


def _response(category: Category) -> list[dict]:
    return [
        {
            "category_id": category.category_id,
            "category_name": category.name,
            "current_budget": 500.0,
            "recommended_budget": 650.0,
            "confidence_level": "medium",
            "behavior_group": "behavior_cluster_0",
            "cluster_label": "behavior_cluster_0",
            "reason": "Clean spending has been over budget recently, so the recommendation increases the category budget.",
            "expected_change_amount": 150.0,
            "expected_change_percent": 0.3,
            "months_used": 4,
        }
    ]


def test_budget_recommendations_require_auth(db_session):
    client = _client(db_session)

    try:
        response = client.get("/budgets/recommendations")
        assert response.status_code == 401
    finally:
        app.dependency_overrides.clear()


def test_authenticated_user_gets_budget_recommendations(db_session, monkeypatch):
    user = _create_user(db_session)
    category = Category(user_id=user.user_id, name="Marketing", type="expense")
    db_session.add(category)
    db_session.commit()
    db_session.refresh(category)

    fake = FakeBudgetRecommender(_response(category))
    monkeypatch.setattr(budgets_api, "budget_recommender", fake)
    client = _client(db_session, user)

    try:
        response = client.get("/budgets/recommendations")
        assert response.status_code == 200
        assert response.json()[0]["category_id"] == category.category_id
        assert fake.calls == [user.user_id]
    finally:
        app.dependency_overrides.clear()


def test_budget_recommendation_api_response_schema(db_session, monkeypatch):
    user = _create_user(db_session)
    category = Category(user_id=user.user_id, name="Software", type="expense")
    db_session.add(category)
    db_session.commit()
    db_session.refresh(category)

    monkeypatch.setattr(budgets_api, "budget_recommender", FakeBudgetRecommender(_response(category)))
    client = _client(db_session, user)

    try:
        response = client.get("/budgets/recommendations")
        assert response.status_code == 200
        body = response.json()[0]
        assert set(body.keys()) == {
            "category_id",
            "category_name",
            "current_budget",
            "recommended_budget",
            "confidence_level",
            "behavior_group",
            "cluster_label",
            "reason",
            "expected_change_amount",
            "expected_change_percent",
            "months_used",
        }
    finally:
        app.dependency_overrides.clear()


def test_budget_recommendation_endpoint_creates_no_budget_records(db_session, monkeypatch):
    user = _create_user(db_session)
    category = Category(user_id=user.user_id, name="Rent", type="expense")
    db_session.add(category)
    db_session.commit()
    db_session.refresh(category)

    before_count = db_session.query(Budget).filter(Budget.user_id == user.user_id).count()
    monkeypatch.setattr(budgets_api, "budget_recommender", FakeBudgetRecommender(_response(category)))
    client = _client(db_session, user)

    try:
        response = client.get("/budgets/recommendations")
        after_count = db_session.query(Budget).filter(Budget.user_id == user.user_id).count()
        assert response.status_code == 200
        assert after_count == before_count
    finally:
        app.dependency_overrides.clear()
