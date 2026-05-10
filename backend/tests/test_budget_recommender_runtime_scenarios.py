from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

import joblib
from fastapi.testclient import TestClient

import app.api.budgets as budgets_api
from app.core.security import create_access_token
from app.db.session import get_db
from app.main import app
from app.models.ai_insight import AIInsight
from app.models.budget import Budget
from app.models.category import Category
from app.models.transaction import Transaction
from app.models.user import User
from app.services.budget_recommender import MODEL_FEATURE_COLUMNS, MODEL_FAMILY, BudgetRecommender


class RuntimeScenarioModel:
    def predict(self, rows: list[dict[str, Any]]) -> list[float]:
        predictions: list[float] = []
        for row in rows:
            clean_spend = float(row["clean_monthly_spend"])
            current_budget = float(row["current_budget"])
            avg_3 = float(row["avg_3_month_spend"])
            growth = float(row["growth_rate_3m"])
            overspend = float(row["overspend_amount"])
            months_over_budget = float(row["months_over_budget_3"])

            if growth > 0.20 or months_over_budget >= 2:
                predictions.append(max(current_budget * 1.20, clean_spend * 1.12, avg_3 * 1.15))
            elif overspend > 0:
                predictions.append(max(current_budget + overspend * 0.60, clean_spend * 1.05))
            else:
                predictions.append(max(50.0, min(current_budget, avg_3 * 1.05)))
        return predictions


class RuntimeScenarioCluster:
    def predict(self, rows: list[list[float]]) -> list[int]:
        labels: list[int] = []
        for row in rows:
            budget_usage_ratio = float(row[5])
            growth_rate = float(row[4])
            labels.append(1 if budget_usage_ratio > 1.0 or growth_rate > 0.20 else 0)
        return labels


def _write_runtime_artifact(tmp_path: Path) -> Path:
    model_path = tmp_path / "budget_recommender.joblib"
    joblib.dump(
        {
            "regressor": RuntimeScenarioModel(),
            "model_name": "Runtime Scenario Budget Recommender",
            "model_family": MODEL_FAMILY,
            "feature_columns": MODEL_FEATURE_COLUMNS,
            "cluster_feature_columns": [
                "clean_monthly_spend",
                "current_budget",
                "avg_3_month_spend",
                "avg_6_month_spend",
                "growth_rate_3m",
                "budget_usage_ratio",
                "overspend_amount",
                "months_over_budget_3",
                "months_over_budget_6",
                "category_share_of_total",
                "total_clean_expense",
            ],
            "cluster_pipeline": RuntimeScenarioCluster(),
            "cluster_labels": ["stable_runtime_group", "pressure_runtime_group"],
            "metadata": {"model_family": MODEL_FAMILY},
        },
        model_path,
    )
    return model_path


def _runtime_recommender(tmp_path: Path) -> BudgetRecommender:
    return BudgetRecommender(model_path=_write_runtime_artifact(tmp_path))


def _create_user(db_session, *, email: str = "runtime-scenario@example.com") -> User:
    user = User(name="Runtime Scenario User", email=email, password_hash="x")
    db_session.add(user)
    db_session.flush()
    return user


def _category(db_session, *, user: User, name: str, category_type: str = "expense") -> Category:
    category = Category(user_id=user.user_id, name=name, type=category_type)
    db_session.add(category)
    db_session.flush()
    return category


def _transaction(
    db_session,
    *,
    user: User,
    category: Category,
    amount: float,
    tx_date: date,
    tx_type: str = "expense",
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


def _budget(db_session, *, user: User, category: Category, amount: float, month: date) -> Budget:
    budget = Budget(
        user_id=user.user_id,
        category_id=category.category_id,
        amount=amount,
        month=month,
    )
    db_session.add(budget)
    db_session.flush()
    return budget


def _add_month(
    db_session,
    *,
    user: User,
    category: Category,
    amount: float,
    budget_amount: float,
    month: date,
) -> None:
    _transaction(db_session, user=user, category=category, amount=amount, tx_date=month)
    _budget(db_session, user=user, category=category, amount=budget_amount, month=month)


def _add_unusual_insight(db_session, *, user: User, tx: Transaction, severity: str = "critical") -> None:
    db_session.add(
        AIInsight(
            user_id=user.user_id,
            rule_id="ml_unusual_transaction",
            title="Critical Unusual Transaction Detected",
            message="Unusual transaction detected.",
            severity=severity,
            period_start=tx.date,
            period_end=tx.date,
            metadata_json={"transaction_id": tx.transaction_id},
        )
    )
    db_session.flush()


def _recommendation_for_category(recommendations: list[dict], category_name: str) -> dict:
    return next(item for item in recommendations if item["category_name"] == category_name)


def _authenticated_client(db_session, user: User) -> TestClient:
    app.dependency_overrides[get_db] = lambda: db_session
    client = TestClient(app)
    client.cookies.set("access_token", create_access_token(str(user.user_id)))
    return client


def test_runtime_scenario_stable_budget_account(db_session, tmp_path: Path) -> None:
    recommender = _runtime_recommender(tmp_path)
    user = _create_user(db_session)
    rent = _category(db_session, user=user, name="Rent")
    for month, amount in [
        (date(2026, 1, 1), 2480.0),
        (date(2026, 2, 1), 2520.0),
        (date(2026, 3, 1), 2490.0),
        (date(2026, 4, 1), 2510.0),
    ]:
        _add_month(db_session, user=user, category=rent, amount=amount, budget_amount=3000.0, month=month)
    db_session.commit()

    recommendation = _recommendation_for_category(recommender.recommend_budgets_for_user(db_session, user), "Rent")

    assert 2500.0 <= recommendation["recommended_budget"] <= 3000.0
    assert recommendation["recommended_budget"] <= recommendation["current_budget"] * 1.10
    assert recommendation["confidence_level"] in {"medium", "high"}


def test_runtime_scenario_growing_marketing(db_session, tmp_path: Path) -> None:
    recommender = _runtime_recommender(tmp_path)
    user = _create_user(db_session)
    marketing = _category(db_session, user=user, name="Marketing")
    for month, amount in [
        (date(2026, 1, 1), 1800.0),
        (date(2026, 2, 1), 2300.0),
        (date(2026, 3, 1), 2900.0),
        (date(2026, 4, 1), 3400.0),
    ]:
        _add_month(db_session, user=user, category=marketing, amount=amount, budget_amount=2500.0, month=month)
    db_session.commit()

    recommendation = _recommendation_for_category(recommender.recommend_budgets_for_user(db_session, user), "Marketing")

    assert recommendation["recommended_budget"] > 2500.0
    assert "overspending" in recommendation["reason"].lower() or "growth" in recommendation["reason"].lower()


def test_runtime_scenario_software_repeatedly_over_budget(db_session, tmp_path: Path) -> None:
    recommender = _runtime_recommender(tmp_path)
    user = _create_user(db_session)
    software = _category(db_session, user=user, name="Software")
    for month, amount in [
        (date(2026, 1, 1), 1200.0),
        (date(2026, 2, 1), 1600.0),
        (date(2026, 3, 1), 1900.0),
        (date(2026, 4, 1), 2300.0),
    ]:
        _add_month(db_session, user=user, category=software, amount=amount, budget_amount=1500.0, month=month)
    db_session.commit()

    recommendation = _recommendation_for_category(recommender.recommend_budgets_for_user(db_session, user), "Software")

    assert recommendation["recommended_budget"] > 1500.0
    assert "overspending" in recommendation["reason"].lower() or "growth" in recommendation["reason"].lower()


def test_runtime_scenario_unusual_spike_exclusion(db_session, tmp_path: Path) -> None:
    recommender = _runtime_recommender(tmp_path)
    user = _create_user(db_session)
    marketing = _category(db_session, user=user, name="Marketing")
    for month, amount in [
        (date(2026, 1, 1), 2500.0),
        (date(2026, 2, 1), 2800.0),
        (date(2026, 3, 1), 3200.0),
        (date(2026, 4, 1), 3500.0),
    ]:
        _add_month(db_session, user=user, category=marketing, amount=amount, budget_amount=3000.0, month=month)
    suspicious_tx = _transaction(
        db_session,
        user=user,
        category=marketing,
        amount=45_000.0,
        tx_date=date(2026, 4, 20),
    )
    _add_unusual_insight(db_session, user=user, tx=suspicious_tx, severity="critical")
    db_session.commit()

    recommendation = _recommendation_for_category(recommender.recommend_budgets_for_user(db_session, user), "Marketing")

    assert recommendation["recommended_budget"] < 10_000.0
    assert recommendation["recommended_budget"] < 45_000.0
    assert recommendation["recommended_budget"] <= 6000.0


def test_runtime_scenario_insufficient_history_returns_safe_fallback(db_session, tmp_path: Path) -> None:
    recommender = _runtime_recommender(tmp_path)
    user = _create_user(db_session)
    rent = _category(db_session, user=user, name="Rent")
    _add_month(db_session, user=user, category=rent, amount=2500.0, budget_amount=3000.0, month=date(2026, 4, 1))
    db_session.commit()

    recommendation = _recommendation_for_category(recommender.recommend_budgets_for_user(db_session, user), "Rent")

    assert recommendation["confidence_level"] == "low"
    assert recommendation["behavior_group"] == "fallback"
    assert recommendation["recommended_budget"] > 0.0


def test_runtime_endpoint_response_is_stable_and_read_only(db_session, tmp_path: Path, monkeypatch) -> None:
    recommender = _runtime_recommender(tmp_path)
    user = _create_user(db_session)
    rent = _category(db_session, user=user, name="Rent")
    for month, amount in [
        (date(2026, 1, 1), 2480.0),
        (date(2026, 2, 1), 2520.0),
        (date(2026, 3, 1), 2490.0),
        (date(2026, 4, 1), 2510.0),
    ]:
        _add_month(db_session, user=user, category=rent, amount=amount, budget_amount=3000.0, month=month)
    db_session.commit()

    before_budgets = db_session.query(Budget).filter(Budget.user_id == user.user_id).count()
    monkeypatch.setattr(budgets_api, "budget_recommender", recommender)
    client = _authenticated_client(db_session, user)

    try:
        response = client.get("/budgets/recommendations")
        after_budgets = db_session.query(Budget).filter(Budget.user_id == user.user_id).count()
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert set(body[0].keys()) == {
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
    assert after_budgets == before_budgets
    assert db_session.query(Budget).filter(Budget.user_id == user.user_id, Budget.category_id == rent.category_id).count() == 4
