from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

import joblib

from app.models.ai_insight import AIInsight
from app.models.budget import Budget
from app.models.category import Category
from app.models.transaction import Transaction
from app.models.user import User
from app.services.budget_recommender import (
    MODEL_FEATURE_COLUMNS,
    MODEL_FAMILY,
    BudgetRecommender,
)


class CleanSpendModel:
    def predict(self, rows: list[dict[str, Any]]) -> list[float]:
        return [
            max(float(row["clean_monthly_spend"]), float(row["current_budget"]))
            for row in rows
        ]


class ClusterZero:
    def predict(self, rows: list[list[float]]) -> list[int]:
        return [0 for _row in rows]


def _write_artifact(tmp_path: Path, model: object | None = None) -> Path:
    model_path = tmp_path / "budget_recommender.joblib"
    joblib.dump(
        {
            "regressor": model or CleanSpendModel(),
            "model_name": "Test Budget Recommender",
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
            "cluster_pipeline": ClusterZero(),
            "cluster_labels": ["behavior_cluster_0"],
            "metadata": {"model_family": MODEL_FAMILY},
        },
        model_path,
    )
    return model_path


def _create_user(db_session, *, email: str = "budget-rec@example.com") -> User:
    user = User(name="Budget Rec", email=email, password_hash="x")
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


def _unusual_insight(db_session, *, user: User, tx: Transaction, severity: str = "warning") -> None:
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
    db_session.flush()


def _add_month(
    db_session,
    *,
    user: User,
    category: Category,
    amount: float,
    month: date,
    budget_amount: float,
) -> None:
    _transaction(db_session, user=user, category=category, amount=amount, tx_date=month)
    _budget(db_session, user=user, category=category, amount=budget_amount, month=month)


def test_service_returns_recommendations_for_user_expense_categories(db_session, tmp_path: Path) -> None:
    recommender = BudgetRecommender(model_path=_write_artifact(tmp_path))
    user = _create_user(db_session)
    marketing = _category(db_session, user=user, name="Marketing")
    _add_month(db_session, user=user, category=marketing, amount=300.0, month=date(2026, 4, 1), budget_amount=250.0)
    _add_month(db_session, user=user, category=marketing, amount=350.0, month=date(2026, 5, 1), budget_amount=275.0)
    db_session.commit()

    recommendations = recommender.recommend_budgets_for_user(db_session, user)

    assert len(recommendations) == 1
    assert recommendations[0]["category_id"] == marketing.category_id
    assert recommendations[0]["recommended_budget"] > 0
    assert recommendations[0]["confidence_level"] == "low"


def test_user_only_sees_own_categories(db_session, tmp_path: Path) -> None:
    recommender = BudgetRecommender(model_path=_write_artifact(tmp_path))
    user = _create_user(db_session, email="owner@example.com")
    other_user = _create_user(db_session, email="other@example.com")
    marketing = _category(db_session, user=user, name="Marketing")
    other_category = _category(db_session, user=other_user, name="Other Marketing")
    _add_month(db_session, user=user, category=marketing, amount=300.0, month=date(2026, 4, 1), budget_amount=250.0)
    _add_month(db_session, user=user, category=marketing, amount=350.0, month=date(2026, 5, 1), budget_amount=275.0)
    _add_month(db_session, user=other_user, category=other_category, amount=999.0, month=date(2026, 5, 1), budget_amount=900.0)
    db_session.commit()

    recommendations = recommender.recommend_budgets_for_user(db_session, user)

    assert {item["category_id"] for item in recommendations} == {marketing.category_id}


def test_income_categories_are_excluded(db_session, tmp_path: Path) -> None:
    recommender = BudgetRecommender(model_path=_write_artifact(tmp_path))
    user = _create_user(db_session)
    income = _category(db_session, user=user, name="Sales", category_type="income")
    marketing = _category(db_session, user=user, name="Marketing")
    _transaction(db_session, user=user, category=income, amount=3000.0, tx_date=date(2026, 5, 1), tx_type="income")
    _add_month(db_session, user=user, category=marketing, amount=300.0, month=date(2026, 4, 1), budget_amount=250.0)
    _add_month(db_session, user=user, category=marketing, amount=350.0, month=date(2026, 5, 1), budget_amount=275.0)
    db_session.commit()

    recommendations = recommender.recommend_budgets_for_user(db_session, user)

    assert all(item["category_name"] != "Sales" for item in recommendations)
    assert {item["category_name"] for item in recommendations} == {"Marketing"}


def test_unusual_transactions_are_excluded(db_session, tmp_path: Path) -> None:
    recommender = BudgetRecommender(model_path=_write_artifact(tmp_path))
    user = _create_user(db_session)
    software = _category(db_session, user=user, name="Software")
    _add_month(db_session, user=user, category=software, amount=200.0, month=date(2026, 4, 1), budget_amount=250.0)
    _transaction(db_session, user=user, category=software, amount=100.0, tx_date=date(2026, 5, 2))
    unusual_tx = _transaction(db_session, user=user, category=software, amount=10_000.0, tx_date=date(2026, 5, 3))
    _budget(db_session, user=user, category=software, amount=250.0, month=date(2026, 5, 1))
    _unusual_insight(db_session, user=user, tx=unusual_tx, severity="critical")
    db_session.commit()

    recommendations = recommender.recommend_budgets_for_user(db_session, user)

    assert recommendations[0]["recommended_budget"] < 1000.0
    assert recommendations[0]["expected_change_amount"] <= 0.0


def test_model_unavailable_does_not_crash(db_session, tmp_path: Path) -> None:
    recommender = BudgetRecommender(model_path=tmp_path / "missing.joblib")
    user = _create_user(db_session)
    marketing = _category(db_session, user=user, name="Marketing")
    _add_month(db_session, user=user, category=marketing, amount=300.0, month=date(2026, 5, 1), budget_amount=350.0)
    db_session.commit()

    recommendations = recommender.recommend_budgets_for_user(db_session, user)

    assert recommendations[0]["confidence_level"] == "unavailable"
    assert recommendations[0]["recommended_budget"] > 0


def test_insufficient_history_returns_low_confidence_fallback(db_session, tmp_path: Path) -> None:
    recommender = BudgetRecommender(model_path=_write_artifact(tmp_path))
    user = _create_user(db_session)
    rent = _category(db_session, user=user, name="Rent")
    _add_month(db_session, user=user, category=rent, amount=1200.0, month=date(2026, 5, 1), budget_amount=1300.0)
    db_session.commit()

    recommendations = recommender.recommend_budgets_for_user(db_session, user)

    assert recommendations[0]["confidence_level"] == "low"
    assert recommendations[0]["behavior_group"] == "fallback"
    assert recommendations[0]["months_used"] == 1


def test_response_schema_contains_frontend_friendly_fields(db_session, tmp_path: Path) -> None:
    recommender = BudgetRecommender(model_path=_write_artifact(tmp_path))
    user = _create_user(db_session)
    travel = _category(db_session, user=user, name="Travel")
    _add_month(db_session, user=user, category=travel, amount=200.0, month=date(2026, 4, 1), budget_amount=250.0)
    _add_month(db_session, user=user, category=travel, amount=220.0, month=date(2026, 5, 1), budget_amount=250.0)
    db_session.commit()

    recommendations = recommender.recommend_budgets_for_user(db_session, user)

    assert set(recommendations[0].keys()) == {
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
