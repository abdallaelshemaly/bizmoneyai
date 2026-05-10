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
    BUDGET_RECOMMENDATION_RULE_ID,
    MODEL_FEATURE_COLUMNS,
    MODEL_FAMILY,
    BudgetRecommender,
)


class MeaningfulBudgetModel:
    def predict(self, rows: list[dict[str, Any]]) -> list[float]:
        return [max(float(row["current_budget"]) * 1.45, float(row["clean_monthly_spend"]) * 1.10) for row in rows]


class TinyBudgetModel:
    def predict(self, rows: list[dict[str, Any]]) -> list[float]:
        return [float(row["current_budget"]) * 1.04 for row in rows]


class ClusterZero:
    def predict(self, rows: list[list[float]]) -> list[int]:
        return [0 for _row in rows]


def _write_artifact(tmp_path: Path, model: object) -> Path:
    model_path = tmp_path / "budget_recommender.joblib"
    joblib.dump(
        {
            "regressor": model,
            "model_name": "Insight Test Budget Recommender",
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
            "cluster_labels": ["budget_pressure_group"],
            "metadata": {"model_family": MODEL_FAMILY},
        },
        model_path,
    )
    return model_path


def _create_user(db_session, *, email: str = "budget-insight@example.com") -> User:
    user = User(name="Budget Insight User", email=email, password_hash="x")
    db_session.add(user)
    db_session.flush()
    return user


def _category(db_session, *, user: User, name: str) -> Category:
    category = Category(user_id=user.user_id, name=name, type="expense")
    db_session.add(category)
    db_session.flush()
    return category


def _add_month(
    db_session,
    *,
    user: User,
    category: Category,
    amount: float,
    budget_amount: float,
    month: date,
) -> None:
    db_session.add(
        Transaction(
            user_id=user.user_id,
            category_id=category.category_id,
            amount=amount,
            type="expense",
            description=f"{category.name} transaction",
            date=month,
        )
    )
    db_session.add(
        Budget(
            user_id=user.user_id,
            category_id=category.category_id,
            amount=budget_amount,
            month=month,
        )
    )
    db_session.flush()


def _add_growing_marketing_history(db_session, *, user: User, category: Category) -> None:
    for month, amount in [
        (date(2026, 1, 1), 1800.0),
        (date(2026, 2, 1), 2300.0),
        (date(2026, 3, 1), 2900.0),
        (date(2026, 4, 1), 3400.0),
    ]:
        _add_month(db_session, user=user, category=category, amount=amount, budget_amount=2500.0, month=month)


def _add_stable_history(db_session, *, user: User, category: Category) -> None:
    for month, amount in [
        (date(2026, 1, 1), 2480.0),
        (date(2026, 2, 1), 2520.0),
        (date(2026, 3, 1), 2490.0),
        (date(2026, 4, 1), 2510.0),
    ]:
        _add_month(db_session, user=user, category=category, amount=amount, budget_amount=3000.0, month=month)


def _budget_recommendation_insights(db_session, user: User) -> list[AIInsight]:
    return (
        db_session.query(AIInsight)
        .filter(AIInsight.user_id == user.user_id, AIInsight.rule_id == BUDGET_RECOMMENDATION_RULE_ID)
        .all()
    )


def test_meaningful_recommendation_creates_insight(db_session, tmp_path: Path) -> None:
    recommender = BudgetRecommender(model_path=_write_artifact(tmp_path, MeaningfulBudgetModel()))
    user = _create_user(db_session)
    marketing = _category(db_session, user=user, name="Marketing")
    _add_growing_marketing_history(db_session, user=user, category=marketing)
    db_session.commit()

    recommendations = recommender.recommend_budgets_for_user(db_session, user)
    insights = _budget_recommendation_insights(db_session, user)

    assert recommendations[0]["recommended_budget"] > recommendations[0]["current_budget"]
    assert len(insights) == 1
    assert insights[0].rule_id == BUDGET_RECOMMENDATION_RULE_ID
    assert insights[0].period_start == date(2026, 5, 1)


def test_tiny_recommendation_does_not_create_noisy_insight(db_session, tmp_path: Path) -> None:
    recommender = BudgetRecommender(model_path=_write_artifact(tmp_path, TinyBudgetModel()))
    user = _create_user(db_session)
    rent = _category(db_session, user=user, name="Rent")
    _add_stable_history(db_session, user=user, category=rent)
    db_session.commit()

    recommender.recommend_budgets_for_user(db_session, user)

    assert _budget_recommendation_insights(db_session, user) == []


def test_duplicate_budget_recommendation_insight_is_not_created(db_session, tmp_path: Path) -> None:
    recommender = BudgetRecommender(model_path=_write_artifact(tmp_path, MeaningfulBudgetModel()))
    user = _create_user(db_session)
    marketing = _category(db_session, user=user, name="Marketing")
    _add_growing_marketing_history(db_session, user=user, category=marketing)
    db_session.commit()

    recommender.recommend_budgets_for_user(db_session, user)
    recommender.recommend_budgets_for_user(db_session, user)

    insights = _budget_recommendation_insights(db_session, user)
    assert len(insights) == 1


def test_budget_recommendation_insight_severity_values_are_valid(db_session, tmp_path: Path) -> None:
    recommender = BudgetRecommender(model_path=_write_artifact(tmp_path, MeaningfulBudgetModel()))
    user = _create_user(db_session)
    marketing = _category(db_session, user=user, name="Marketing")
    _add_growing_marketing_history(db_session, user=user, category=marketing)
    db_session.commit()

    recommender.recommend_budgets_for_user(db_session, user)
    insight = _budget_recommendation_insights(db_session, user)[0]

    assert insight.severity in {"info", "warning", "critical"}
    assert insight.severity == "warning"


def test_budget_recommendation_insight_message_is_user_friendly(db_session, tmp_path: Path) -> None:
    recommender = BudgetRecommender(model_path=_write_artifact(tmp_path, MeaningfulBudgetModel()))
    user = _create_user(db_session)
    marketing = _category(db_session, user=user, name="Marketing")
    _add_growing_marketing_history(db_session, user=user, category=marketing)
    db_session.commit()

    recommender.recommend_budgets_for_user(db_session, user)
    message = _budget_recommendation_insights(db_session, user)[0].message

    assert "Your Marketing budget may be too low for next month." in message
    assert "Recommended budget:" in message
    assert "recent growth" in message or "repeated overspending" in message
    assert "feature" not in message.lower()


def test_budget_recommendation_insight_metadata_includes_budget_context(db_session, tmp_path: Path) -> None:
    recommender = BudgetRecommender(model_path=_write_artifact(tmp_path, MeaningfulBudgetModel()))
    user = _create_user(db_session)
    marketing = _category(db_session, user=user, name="Marketing")
    _add_growing_marketing_history(db_session, user=user, category=marketing)
    db_session.commit()

    recommender.recommend_budgets_for_user(db_session, user)
    metadata = _budget_recommendation_insights(db_session, user)[0].metadata_json

    assert metadata is not None
    assert metadata["category_id"] == marketing.category_id
    assert metadata["current_budget"] == 2500.0
    assert metadata["recommended_budget"] > metadata["current_budget"]
    assert metadata["expected_change_percent"] >= 0.15
    assert metadata["scope_key"] == f"category:{marketing.category_id}:target_month:2026-05-01"
