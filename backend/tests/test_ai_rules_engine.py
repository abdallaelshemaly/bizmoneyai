from datetime import date

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401
from app.db.session import Base
from app.models.ai_insight import AIInsight
from app.models.budget import Budget
from app.models.category import Category
from app.models.transaction import Transaction
from app.models.user import User
from app.services.insights import rules as rules_module
from app.services.rules_engine import run_rules_for_user


@pytest.fixture()
def db_session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    db = TestingSessionLocal()

    try:
        yield db
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)


def _create_user(db_session, *, name: str, email: str) -> User:
    user = User(name=name, email=email, password_hash="x")
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


def _create_category(db_session, *, user_id: int, name: str, category_type: str) -> Category:
    category = Category(user_id=user_id, name=name, type=category_type)
    db_session.add(category)
    db_session.commit()
    db_session.refresh(category)
    return category


def _add_transactions(db_session, *transactions: Transaction) -> None:
    db_session.add_all(list(transactions))
    db_session.commit()


def _add_budgets(db_session, *budgets: Budget) -> None:
    db_session.add_all(list(budgets))
    db_session.commit()


def test_run_rules_for_user_generates_modular_insights_and_dedupes(db_session):
    user = User(name="Insight User", email="insight@example.com", password_hash="x")
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)

    sales = Category(user_id=user.user_id, name="Sales", type="income")
    marketing = Category(user_id=user.user_id, name="Marketing", type="expense")
    travel = Category(user_id=user.user_id, name="Travel", type="expense")
    operations = Category(user_id=user.user_id, name="Operations", type="expense")
    db_session.add_all([sales, marketing, travel, operations])
    db_session.commit()
    db_session.refresh(sales)
    db_session.refresh(marketing)
    db_session.refresh(travel)
    db_session.refresh(operations)

    db_session.add_all(
        [
            Budget(
                user_id=user.user_id,
                category_id=marketing.category_id,
                amount=700.0,
                month=date(2026, 3, 1),
                note="March marketing",
            ),
            Budget(
                user_id=user.user_id,
                category_id=marketing.category_id,
                amount=600.0,
                month=date(2026, 4, 1),
                note="April marketing",
            ),
            Budget(
                user_id=user.user_id,
                category_id=operations.category_id,
                amount=500.0,
                month=date(2026, 4, 1),
                note="April operations",
            ),
        ]
    )
    db_session.commit()

    db_session.add_all(
        [
            Transaction(
                user_id=user.user_id,
                category_id=sales.category_id,
                amount=4000.0,
                type="income",
                description="March sales",
                date=date(2026, 3, 15),
            ),
            Transaction(
                user_id=user.user_id,
                category_id=marketing.category_id,
                amount=900.0,
                type="expense",
                description="March ads",
                date=date(2026, 3, 18),
            ),
            Transaction(
                user_id=user.user_id,
                category_id=operations.category_id,
                amount=100.0,
                type="expense",
                description="March tooling",
                date=date(2026, 3, 20),
            ),
            Transaction(
                user_id=user.user_id,
                category_id=sales.category_id,
                amount=1800.0,
                type="income",
                description="April sales",
                date=date(2026, 4, 12),
            ),
            Transaction(
                user_id=user.user_id,
                category_id=marketing.category_id,
                amount=1000.0,
                type="expense",
                description="April ads",
                date=date(2026, 4, 16),
            ),
            Transaction(
                user_id=user.user_id,
                category_id=travel.category_id,
                amount=600.0,
                type="expense",
                description="Conference travel",
                date=date(2026, 4, 19),
            ),
            Transaction(
                user_id=user.user_id,
                category_id=operations.category_id,
                amount=350.0,
                type="expense",
                description="Office tools",
                date=date(2026, 4, 23),
            ),
        ]
    )
    db_session.commit()

    created = run_rules_for_user(
        db_session,
        user.user_id,
        date(2026, 4, 1),
        date(2026, 4, 30),
    )

    created_rule_ids = {insight.rule_id for insight in created}
    assert {
        "negative_balance",
        "expense_ratio",
        "profit_drop_percent",
        "spending_spike_percent",
        "budget_overspend_ratio",
        "category_income_ratio",
        "income_drop_percent",
        "missing_budget_high_spend",
        "consecutive_budget_overspend",
    }.issubset(created_rule_ids)

    marketing_budget_insight = next(
        insight
        for insight in created
        if insight.rule_id == "budget_overspend_ratio" and (insight.metadata_json or {}).get("category_name") == "Marketing"
    )
    assert marketing_budget_insight.severity == "critical"
    assert marketing_budget_insight.metadata_json is not None
    assert marketing_budget_insight.metadata_json["budget_month"] == "2026-04-01"
    assert marketing_budget_insight.metadata_json["scope_key"] == f"category:{marketing.category_id}:month:2026-04-01"

    rerun = run_rules_for_user(
        db_session,
        user.user_id,
        date(2026, 4, 1),
        date(2026, 4, 30),
    )
    assert rerun == []


def test_run_rules_for_user_returns_no_insights_when_period_has_no_transactions(db_session):
    user = _create_user(db_session, name="Empty Period User", email="empty-period@example.com")

    created = run_rules_for_user(
        db_session,
        user.user_id,
        date(2026, 4, 1),
        date(2026, 4, 30),
    )

    assert created == []


def test_comparison_rules_do_not_trigger_when_previous_period_is_missing(db_session):
    user = _create_user(db_session, name="No Previous Period User", email="no-previous-period@example.com")
    income = _create_category(db_session, user_id=user.user_id, name="Sales", category_type="income")

    _add_transactions(
        db_session,
        Transaction(
            user_id=user.user_id,
            category_id=income.category_id,
            amount=1500.0,
            type="income",
            description="Current revenue only",
            date=date(2026, 4, 10),
        ),
    )

    created = run_rules_for_user(
        db_session,
        user.user_id,
        date(2026, 4, 1),
        date(2026, 4, 30),
    )

    created_rule_ids = {insight.rule_id for insight in created}
    assert "profit_drop_percent" not in created_rule_ids
    assert "income_drop_percent" not in created_rule_ids
    assert "spending_spike_percent" not in created_rule_ids
    assert created == []


def test_run_rules_for_user_uses_explicit_zero_income_rule(db_session):
    user = User(name="Zero Income User", email="zero-income@example.com", password_hash="x")
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)

    expenses = Category(user_id=user.user_id, name="Operations", type="expense")
    db_session.add(expenses)
    db_session.commit()
    db_session.refresh(expenses)

    db_session.add(
        Transaction(
            user_id=user.user_id,
            category_id=expenses.category_id,
            amount=750.0,
            type="expense",
            description="Emergency expense",
            date=date(2026, 4, 10),
        )
    )
    db_session.commit()

    created = run_rules_for_user(
        db_session,
        user.user_id,
        date(2026, 4, 1),
        date(2026, 4, 30),
    )

    zero_income_insight = next(insight for insight in created if insight.rule_id == "zero_income_with_expense")
    assert zero_income_insight.severity == "critical"
    assert zero_income_insight.metadata_json is not None
    assert zero_income_insight.metadata_json["zero_income"] is True
    assert all(insight.rule_id != "expense_ratio" for insight in created)


def test_partial_period_skips_zero_income_rule_when_income_is_outside_selected_range(db_session):
    user = User(name="Partial Zero Income User", email="partial-zero-income@example.com", password_hash="x")
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)

    income = Category(user_id=user.user_id, name="Sales", type="income")
    expenses = Category(user_id=user.user_id, name="Operations", type="expense")
    db_session.add_all([income, expenses])
    db_session.commit()
    db_session.refresh(income)
    db_session.refresh(expenses)

    db_session.add_all(
        [
            Transaction(
                user_id=user.user_id,
                category_id=income.category_id,
                amount=4000.0,
                type="income",
                description="Early month revenue",
                date=date(2026, 4, 2),
            ),
            Transaction(
                user_id=user.user_id,
                category_id=expenses.category_id,
                amount=750.0,
                type="expense",
                description="Mid-month expense",
                date=date(2026, 4, 18),
            ),
        ]
    )
    db_session.commit()

    created = run_rules_for_user(
        db_session,
        user.user_id,
        date(2026, 4, 13),
        date(2026, 4, 30),
    )

    created_rule_ids = {insight.rule_id for insight in created}
    assert "zero_income_with_expense" not in created_rule_ids


def test_expense_ratio_rule_triggers_with_threshold_severity(db_session):
    user = _create_user(db_session, name="Expense Ratio User", email="expense-ratio@example.com")
    income = _create_category(db_session, user_id=user.user_id, name="Sales", category_type="income")
    expense = _create_category(db_session, user_id=user.user_id, name="Operations", category_type="expense")

    _add_transactions(
        db_session,
        Transaction(
            user_id=user.user_id,
            category_id=income.category_id,
            amount=1000.0,
            type="income",
            description="April revenue",
            date=date(2026, 4, 5),
        ),
        Transaction(
            user_id=user.user_id,
            category_id=expense.category_id,
            amount=900.0,
            type="expense",
            description="April operating cost",
            date=date(2026, 4, 6),
        ),
    )

    created = run_rules_for_user(
        db_session,
        user.user_id,
        date(2026, 4, 1),
        date(2026, 4, 30),
    )

    expense_ratio_insight = next(insight for insight in created if insight.rule_id == "expense_ratio")
    assert expense_ratio_insight.severity == "warning"
    assert expense_ratio_insight.metadata_json is not None
    assert expense_ratio_insight.metadata_json["expense_ratio"] == 0.9


@pytest.mark.parametrize(
    ("expense_amount", "expected_severity"),
    [
        (720.0, "info"),
        (900.0, "warning"),
        (1100.0, "critical"),
    ],
)
def test_expense_ratio_rule_matches_phase_one_thresholds(db_session, expense_amount, expected_severity):
    user = _create_user(
        db_session,
        name=f"Expense Ratio {expected_severity.title()} User",
        email=f"expense-ratio-{expected_severity}@example.com",
    )
    income = _create_category(db_session, user_id=user.user_id, name="Sales", category_type="income")
    expense = _create_category(db_session, user_id=user.user_id, name="Operations", category_type="expense")

    _add_transactions(
        db_session,
        Transaction(
            user_id=user.user_id,
            category_id=income.category_id,
            amount=1000.0,
            type="income",
            description="Period revenue",
            date=date(2026, 4, 5),
        ),
        Transaction(
            user_id=user.user_id,
            category_id=expense.category_id,
            amount=expense_amount,
            type="expense",
            description="Period expense",
            date=date(2026, 4, 6),
        ),
    )

    created = run_rules_for_user(db_session, user.user_id, date(2026, 4, 1), date(2026, 4, 30))

    expense_ratio_insight = next(insight for insight in created if insight.rule_id == "expense_ratio")
    assert expense_ratio_insight.severity == expected_severity


def test_profit_drop_percent_rule_triggers_from_previous_period_profit_decline(db_session):
    user = _create_user(db_session, name="Profit Drop User", email="profit-drop@example.com")
    income = _create_category(db_session, user_id=user.user_id, name="Sales", category_type="income")
    expense = _create_category(db_session, user_id=user.user_id, name="Operations", category_type="expense")

    _add_transactions(
        db_session,
        Transaction(
            user_id=user.user_id,
            category_id=income.category_id,
            amount=2000.0,
            type="income",
            description="Previous revenue",
            date=date(2026, 3, 10),
        ),
        Transaction(
            user_id=user.user_id,
            category_id=expense.category_id,
            amount=1200.0,
            type="expense",
            description="Previous operating cost",
            date=date(2026, 3, 12),
        ),
        Transaction(
            user_id=user.user_id,
            category_id=income.category_id,
            amount=1500.0,
            type="income",
            description="Current revenue",
            date=date(2026, 4, 10),
        ),
        Transaction(
            user_id=user.user_id,
            category_id=expense.category_id,
            amount=1300.0,
            type="expense",
            description="Current operating cost",
            date=date(2026, 4, 12),
        ),
    )

    created = run_rules_for_user(
        db_session,
        user.user_id,
        date(2026, 4, 1),
        date(2026, 4, 30),
    )

    profit_drop_insight = next(insight for insight in created if insight.rule_id == "profit_drop_percent")
    assert profit_drop_insight.severity == "critical"
    assert profit_drop_insight.metadata_json is not None
    assert profit_drop_insight.metadata_json["previous_profit"] == 800.0
    assert profit_drop_insight.metadata_json["current_profit"] == 200.0


def test_profit_drop_percent_rule_supports_warning_threshold(db_session):
    user = _create_user(db_session, name="Profit Drop Warning User", email="profit-drop-warning@example.com")
    income = _create_category(db_session, user_id=user.user_id, name="Sales", category_type="income")
    expense = _create_category(db_session, user_id=user.user_id, name="Operations", category_type="expense")

    _add_transactions(
        db_session,
        Transaction(
            user_id=user.user_id,
            category_id=income.category_id,
            amount=2000.0,
            type="income",
            description="Previous revenue",
            date=date(2026, 3, 10),
        ),
        Transaction(
            user_id=user.user_id,
            category_id=expense.category_id,
            amount=1000.0,
            type="expense",
            description="Previous operating cost",
            date=date(2026, 3, 12),
        ),
        Transaction(
            user_id=user.user_id,
            category_id=income.category_id,
            amount=1800.0,
            type="income",
            description="Current revenue",
            date=date(2026, 4, 10),
        ),
        Transaction(
            user_id=user.user_id,
            category_id=expense.category_id,
            amount=1050.0,
            type="expense",
            description="Current operating cost",
            date=date(2026, 4, 12),
        ),
    )

    created = run_rules_for_user(db_session, user.user_id, date(2026, 4, 1), date(2026, 4, 30))

    profit_drop_insight = next(insight for insight in created if insight.rule_id == "profit_drop_percent")
    assert profit_drop_insight.severity == "warning"


def test_full_month_period_with_normal_monthly_data_does_not_create_false_income_or_profit_drop(db_session):
    user = _create_user(db_session, name="Full Month Stable User", email="full-month-stable@example.com")
    income = _create_category(db_session, user_id=user.user_id, name="Sales", category_type="income")
    expense = _create_category(db_session, user_id=user.user_id, name="Operations", category_type="expense")

    _add_transactions(
        db_session,
        Transaction(
            user_id=user.user_id,
            category_id=income.category_id,
            amount=3000.0,
            type="income",
            description="March revenue",
            date=date(2026, 3, 5),
        ),
        Transaction(
            user_id=user.user_id,
            category_id=expense.category_id,
            amount=1000.0,
            type="expense",
            description="March operating cost",
            date=date(2026, 3, 18),
        ),
        Transaction(
            user_id=user.user_id,
            category_id=income.category_id,
            amount=3000.0,
            type="income",
            description="April revenue",
            date=date(2026, 4, 5),
        ),
        Transaction(
            user_id=user.user_id,
            category_id=expense.category_id,
            amount=1000.0,
            type="expense",
            description="April operating cost",
            date=date(2026, 4, 18),
        ),
    )

    created = run_rules_for_user(db_session, user.user_id, date(2026, 4, 1), date(2026, 4, 30))

    created_rule_ids = {insight.rule_id for insight in created}
    assert "income_drop_percent" not in created_rule_ids
    assert "profit_drop_percent" not in created_rule_ids


def test_spending_spike_percent_rule_triggers_from_previous_period_growth(db_session):
    user = _create_user(db_session, name="Spending Spike User", email="spending-spike@example.com")
    income = _create_category(db_session, user_id=user.user_id, name="Sales", category_type="income")
    expense = _create_category(db_session, user_id=user.user_id, name="Operations", category_type="expense")

    _add_transactions(
        db_session,
        Transaction(
            user_id=user.user_id,
            category_id=income.category_id,
            amount=5000.0,
            type="income",
            description="Previous revenue",
            date=date(2026, 3, 8),
        ),
        Transaction(
            user_id=user.user_id,
            category_id=expense.category_id,
            amount=500.0,
            type="expense",
            description="Previous spend",
            date=date(2026, 3, 10),
        ),
        Transaction(
            user_id=user.user_id,
            category_id=income.category_id,
            amount=5000.0,
            type="income",
            description="Current revenue",
            date=date(2026, 4, 8),
        ),
        Transaction(
            user_id=user.user_id,
            category_id=expense.category_id,
            amount=900.0,
            type="expense",
            description="Current spend",
            date=date(2026, 4, 10),
        ),
    )

    created = run_rules_for_user(
        db_session,
        user.user_id,
        date(2026, 4, 1),
        date(2026, 4, 30),
    )

    spending_spike_insight = next(insight for insight in created if insight.rule_id == "spending_spike_percent")
    assert spending_spike_insight.severity == "critical"
    assert spending_spike_insight.metadata_json is not None
    assert spending_spike_insight.metadata_json["previous_expense"] == 500.0
    assert spending_spike_insight.metadata_json["current_expense"] == 900.0


def test_spending_spike_percent_rule_supports_warning_threshold(db_session):
    user = _create_user(db_session, name="Spending Spike Warning User", email="spending-spike-warning@example.com")
    income = _create_category(db_session, user_id=user.user_id, name="Sales", category_type="income")
    expense = _create_category(db_session, user_id=user.user_id, name="Operations", category_type="expense")

    _add_transactions(
        db_session,
        Transaction(
            user_id=user.user_id,
            category_id=income.category_id,
            amount=5000.0,
            type="income",
            description="Previous revenue",
            date=date(2026, 3, 8),
        ),
        Transaction(
            user_id=user.user_id,
            category_id=expense.category_id,
            amount=500.0,
            type="expense",
            description="Previous spend",
            date=date(2026, 3, 10),
        ),
        Transaction(
            user_id=user.user_id,
            category_id=income.category_id,
            amount=5000.0,
            type="income",
            description="Current revenue",
            date=date(2026, 4, 8),
        ),
        Transaction(
            user_id=user.user_id,
            category_id=expense.category_id,
            amount=700.0,
            type="expense",
            description="Current spend",
            date=date(2026, 4, 10),
        ),
    )

    created = run_rules_for_user(db_session, user.user_id, date(2026, 4, 1), date(2026, 4, 30))

    spending_spike_insight = next(insight for insight in created if insight.rule_id == "spending_spike_percent")
    assert spending_spike_insight.severity == "warning"


def test_budget_overspend_ratio_rule_triggers_for_budgeted_category_month(db_session):
    user = _create_user(db_session, name="Budget Overspend User", email="budget-overspend@example.com")
    income = _create_category(db_session, user_id=user.user_id, name="Sales", category_type="income")
    marketing = _create_category(db_session, user_id=user.user_id, name="Marketing", category_type="expense")

    _add_budgets(
        db_session,
        Budget(
            user_id=user.user_id,
            category_id=marketing.category_id,
            amount=1000.0,
            month=date(2026, 4, 1),
            note="April marketing",
        ),
    )
    _add_transactions(
        db_session,
        Transaction(
            user_id=user.user_id,
            category_id=income.category_id,
            amount=6000.0,
            type="income",
            description="April revenue",
            date=date(2026, 4, 7),
        ),
        Transaction(
            user_id=user.user_id,
            category_id=marketing.category_id,
            amount=1300.0,
            type="expense",
            description="April ads",
            date=date(2026, 4, 14),
        ),
    )

    created = run_rules_for_user(
        db_session,
        user.user_id,
        date(2026, 4, 1),
        date(2026, 4, 30),
    )

    overspend_insight = next(insight for insight in created if insight.rule_id == "budget_overspend_ratio")
    assert overspend_insight.severity == "critical"
    assert overspend_insight.metadata_json is not None
    assert overspend_insight.metadata_json["budget_usage_ratio"] == 1.3
    assert overspend_insight.metadata_json["budget_month"] == "2026-04-01"


def test_budget_ratio_rules_ignore_zero_amount_budgets_without_crashing(db_session):
    user = _create_user(db_session, name="Zero Budget User", email="zero-budget@example.com")
    income = _create_category(db_session, user_id=user.user_id, name="Sales", category_type="income")
    marketing = _create_category(db_session, user_id=user.user_id, name="Marketing", category_type="expense")

    _add_budgets(
        db_session,
        Budget(
            user_id=user.user_id,
            category_id=marketing.category_id,
            amount=0.0,
            month=date(2026, 4, 1),
            note="Zeroed budget",
        ),
    )
    _add_transactions(
        db_session,
        Transaction(
            user_id=user.user_id,
            category_id=income.category_id,
            amount=5000.0,
            type="income",
            description="April revenue",
            date=date(2026, 4, 5),
        ),
        Transaction(
            user_id=user.user_id,
            category_id=marketing.category_id,
            amount=50.0,
            type="expense",
            description="Small spend",
            date=date(2026, 4, 6),
        ),
    )

    created = run_rules_for_user(db_session, user.user_id, date(2026, 4, 1), date(2026, 4, 30))

    assert all(insight.rule_id != "budget_overspend_ratio" for insight in created)


@pytest.mark.parametrize(
    ("spent_amount", "expected_severity"),
    [
        (900.0, "info"),
        (1050.0, "warning"),
        (1300.0, "critical"),
    ],
)
def test_budget_overspend_ratio_rule_matches_phase_one_thresholds(db_session, spent_amount, expected_severity):
    user = _create_user(
        db_session,
        name=f"Budget Usage {expected_severity.title()} User",
        email=f"budget-usage-{expected_severity}@example.com",
    )
    income = _create_category(db_session, user_id=user.user_id, name="Sales", category_type="income")
    marketing = _create_category(db_session, user_id=user.user_id, name="Marketing", category_type="expense")

    _add_budgets(
        db_session,
        Budget(
            user_id=user.user_id,
            category_id=marketing.category_id,
            amount=1000.0,
            month=date(2026, 4, 1),
            note="April marketing",
        ),
    )
    _add_transactions(
        db_session,
        Transaction(
            user_id=user.user_id,
            category_id=income.category_id,
            amount=5000.0,
            type="income",
            description="April revenue",
            date=date(2026, 4, 5),
        ),
        Transaction(
            user_id=user.user_id,
            category_id=marketing.category_id,
            amount=spent_amount,
            type="expense",
            description="Marketing spend",
            date=date(2026, 4, 7),
        ),
    )

    created = run_rules_for_user(db_session, user.user_id, date(2026, 4, 1), date(2026, 4, 30))

    overspend_insight = next(insight for insight in created if insight.rule_id == "budget_overspend_ratio")
    assert overspend_insight.severity == expected_severity


def test_category_income_ratio_rule_triggers_for_high_category_share(db_session):
    user = _create_user(db_session, name="Category Ratio User", email="category-ratio@example.com")
    income = _create_category(db_session, user_id=user.user_id, name="Sales", category_type="income")
    travel = _create_category(db_session, user_id=user.user_id, name="Travel", category_type="expense")

    _add_transactions(
        db_session,
        Transaction(
            user_id=user.user_id,
            category_id=income.category_id,
            amount=1000.0,
            type="income",
            description="April revenue",
            date=date(2026, 4, 5),
        ),
        Transaction(
            user_id=user.user_id,
            category_id=travel.category_id,
            amount=450.0,
            type="expense",
            description="April travel",
            date=date(2026, 4, 15),
        ),
    )

    created = run_rules_for_user(
        db_session,
        user.user_id,
        date(2026, 4, 1),
        date(2026, 4, 30),
    )

    category_ratio_insight = next(insight for insight in created if insight.rule_id == "category_income_ratio")
    assert category_ratio_insight.severity == "warning"
    assert category_ratio_insight.metadata_json is not None
    assert category_ratio_insight.metadata_json["category_name"] == "Travel"
    assert category_ratio_insight.metadata_json["category_income_ratio"] == 0.45


def test_income_drop_percent_rule_triggers_without_profit_drop(db_session):
    user = _create_user(db_session, name="Income Drop User", email="income-drop@example.com")
    income = _create_category(db_session, user_id=user.user_id, name="Sales", category_type="income")
    expense = _create_category(db_session, user_id=user.user_id, name="Operations", category_type="expense")

    _add_transactions(
        db_session,
        Transaction(
            user_id=user.user_id,
            category_id=income.category_id,
            amount=2000.0,
            type="income",
            description="Previous revenue",
            date=date(2026, 3, 8),
        ),
        Transaction(
            user_id=user.user_id,
            category_id=expense.category_id,
            amount=1900.0,
            type="expense",
            description="Previous operating cost",
            date=date(2026, 3, 12),
        ),
        Transaction(
            user_id=user.user_id,
            category_id=income.category_id,
            amount=1400.0,
            type="income",
            description="Current revenue",
            date=date(2026, 4, 8),
        ),
        Transaction(
            user_id=user.user_id,
            category_id=expense.category_id,
            amount=1200.0,
            type="expense",
            description="Current operating cost",
            date=date(2026, 4, 14),
        ),
    )

    created = run_rules_for_user(
        db_session,
        user.user_id,
        date(2026, 4, 1),
        date(2026, 4, 30),
    )

    income_drop_insight = next(insight for insight in created if insight.rule_id == "income_drop_percent")
    assert income_drop_insight.severity == "critical"
    assert income_drop_insight.metadata_json is not None
    assert income_drop_insight.metadata_json["previous_income"] == 2000.0
    assert income_drop_insight.metadata_json["current_income"] == 1400.0
    assert all(insight.rule_id != "profit_drop_percent" for insight in created)


def test_income_drop_percent_rule_supports_warning_threshold(db_session):
    user = _create_user(db_session, name="Income Drop Warning User", email="income-drop-warning@example.com")
    income = _create_category(db_session, user_id=user.user_id, name="Sales", category_type="income")
    expense = _create_category(db_session, user_id=user.user_id, name="Operations", category_type="expense")

    _add_transactions(
        db_session,
        Transaction(
            user_id=user.user_id,
            category_id=income.category_id,
            amount=2000.0,
            type="income",
            description="Previous revenue",
            date=date(2026, 3, 8),
        ),
        Transaction(
            user_id=user.user_id,
            category_id=expense.category_id,
            amount=800.0,
            type="expense",
            description="Previous operating cost",
            date=date(2026, 3, 12),
        ),
        Transaction(
            user_id=user.user_id,
            category_id=income.category_id,
            amount=1500.0,
            type="income",
            description="Current revenue",
            date=date(2026, 4, 8),
        ),
        Transaction(
            user_id=user.user_id,
            category_id=expense.category_id,
            amount=800.0,
            type="expense",
            description="Current operating cost",
            date=date(2026, 4, 14),
        ),
    )

    created = run_rules_for_user(db_session, user.user_id, date(2026, 4, 1), date(2026, 4, 30))

    income_drop_insight = next(insight for insight in created if insight.rule_id == "income_drop_percent")
    assert income_drop_insight.severity == "warning"


def test_partial_period_skips_income_and_profit_drop_rules_when_early_month_income_is_outside_range(db_session):
    user = _create_user(db_session, name="Partial Period User", email="partial-period@example.com")
    income = _create_category(db_session, user_id=user.user_id, name="Sales", category_type="income")
    expense = _create_category(db_session, user_id=user.user_id, name="Operations", category_type="expense")

    _add_transactions(
        db_session,
        Transaction(
            user_id=user.user_id,
            category_id=income.category_id,
            amount=3000.0,
            type="income",
            description="April revenue posted early",
            date=date(2026, 4, 5),
        ),
        Transaction(
            user_id=user.user_id,
            category_id=expense.category_id,
            amount=1200.0,
            type="expense",
            description="April operating cost",
            date=date(2026, 4, 18),
        ),
    )

    created = run_rules_for_user(db_session, user.user_id, date(2026, 4, 13), date(2026, 4, 30))

    created_rule_ids = {insight.rule_id for insight in created}
    assert "income_drop_percent" not in created_rule_ids
    assert "profit_drop_percent" not in created_rule_ids


def test_full_month_period_still_triggers_real_income_and_profit_drop_rules(db_session):
    user = _create_user(db_session, name="Real Drop User", email="real-drop@example.com")
    income = _create_category(db_session, user_id=user.user_id, name="Sales", category_type="income")
    expense = _create_category(db_session, user_id=user.user_id, name="Operations", category_type="expense")

    _add_transactions(
        db_session,
        Transaction(
            user_id=user.user_id,
            category_id=income.category_id,
            amount=3000.0,
            type="income",
            description="March revenue",
            date=date(2026, 3, 5),
        ),
        Transaction(
            user_id=user.user_id,
            category_id=expense.category_id,
            amount=1000.0,
            type="expense",
            description="March operating cost",
            date=date(2026, 3, 18),
        ),
        Transaction(
            user_id=user.user_id,
            category_id=income.category_id,
            amount=1200.0,
            type="income",
            description="April revenue",
            date=date(2026, 4, 5),
        ),
        Transaction(
            user_id=user.user_id,
            category_id=expense.category_id,
            amount=1000.0,
            type="expense",
            description="April operating cost",
            date=date(2026, 4, 18),
        ),
    )

    created = run_rules_for_user(db_session, user.user_id, date(2026, 4, 1), date(2026, 4, 30))

    income_drop_insight = next(insight for insight in created if insight.rule_id == "income_drop_percent")
    profit_drop_insight = next(insight for insight in created if insight.rule_id == "profit_drop_percent")
    assert income_drop_insight.severity == "critical"
    assert profit_drop_insight.severity == "critical"
    assert income_drop_insight.metadata_json is not None
    assert income_drop_insight.metadata_json["previous_income"] == 3000.0
    assert income_drop_insight.metadata_json["current_income"] == 1200.0
    assert profit_drop_insight.metadata_json is not None
    assert profit_drop_insight.metadata_json["previous_profit"] == 2000.0
    assert profit_drop_insight.metadata_json["current_profit"] == 200.0


def test_missing_budget_high_spend_evaluates_per_category_per_month(db_session):
    user = User(name="Monthly Budget User", email="monthly-budget@example.com", password_hash="x")
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)

    income = Category(user_id=user.user_id, name="Sales", type="income")
    travel = Category(user_id=user.user_id, name="Travel", type="expense")
    db_session.add_all([income, travel])
    db_session.commit()
    db_session.refresh(income)
    db_session.refresh(travel)

    db_session.add(
        Budget(
            user_id=user.user_id,
            category_id=travel.category_id,
            amount=200.0,
            month=date(2026, 4, 1),
            note="April travel",
        )
    )
    db_session.commit()

    db_session.add_all(
        [
            Transaction(
                user_id=user.user_id,
                category_id=income.category_id,
                amount=2500.0,
                type="income",
                description="Quarterly income",
                date=date(2026, 3, 5),
            ),
            Transaction(
                user_id=user.user_id,
                category_id=travel.category_id,
                amount=600.0,
                type="expense",
                description="March travel",
                date=date(2026, 3, 10),
            ),
            Transaction(
                user_id=user.user_id,
                category_id=travel.category_id,
                amount=100.0,
                type="expense",
                description="April travel",
                date=date(2026, 4, 12),
            ),
        ]
    )
    db_session.commit()

    created = run_rules_for_user(
        db_session,
        user.user_id,
        date(2026, 3, 1),
        date(2026, 4, 30),
    )

    missing_budget_insights = [insight for insight in created if insight.rule_id == "missing_budget_high_spend"]
    assert len(missing_budget_insights) == 1
    assert missing_budget_insights[0].metadata_json is not None
    assert missing_budget_insights[0].metadata_json["spend_month"] == "2026-03-01"
    assert missing_budget_insights[0].metadata_json["scope_key"] == f"category:{travel.category_id}:month:2026-03-01"


def test_consecutive_budget_overspend_rule_triggers_for_repeated_months(db_session):
    user = _create_user(db_session, name="Consecutive Overspend User", email="consecutive-overspend@example.com")
    income = _create_category(db_session, user_id=user.user_id, name="Sales", category_type="income")
    marketing = _create_category(db_session, user_id=user.user_id, name="Marketing", category_type="expense")

    _add_budgets(
        db_session,
        Budget(
            user_id=user.user_id,
            category_id=marketing.category_id,
            amount=100.0,
            month=date(2026, 2, 1),
            note="February marketing",
        ),
        Budget(
            user_id=user.user_id,
            category_id=marketing.category_id,
            amount=100.0,
            month=date(2026, 3, 1),
            note="March marketing",
        ),
        Budget(
            user_id=user.user_id,
            category_id=marketing.category_id,
            amount=100.0,
            month=date(2026, 4, 1),
            note="April marketing",
        ),
    )
    _add_transactions(
        db_session,
        Transaction(
            user_id=user.user_id,
            category_id=income.category_id,
            amount=1000.0,
            type="income",
            description="April revenue",
            date=date(2026, 4, 6),
        ),
        Transaction(
            user_id=user.user_id,
            category_id=marketing.category_id,
            amount=150.0,
            type="expense",
            description="February overspend",
            date=date(2026, 2, 10),
        ),
        Transaction(
            user_id=user.user_id,
            category_id=marketing.category_id,
            amount=150.0,
            type="expense",
            description="March overspend",
            date=date(2026, 3, 10),
        ),
        Transaction(
            user_id=user.user_id,
            category_id=marketing.category_id,
            amount=150.0,
            type="expense",
            description="April overspend",
            date=date(2026, 4, 10),
        ),
    )

    created = run_rules_for_user(
        db_session,
        user.user_id,
        date(2026, 4, 1),
        date(2026, 4, 30),
    )

    consecutive_overspend = next(insight for insight in created if insight.rule_id == "consecutive_budget_overspend")
    assert consecutive_overspend.severity == "warning"
    assert consecutive_overspend.metadata_json is not None
    assert consecutive_overspend.metadata_json["consecutive_overspend_count"] == 3
    assert consecutive_overspend.metadata_json["budget_month"] == "2026-04-01"


@pytest.mark.parametrize(
    ("months", "expected_severity"),
    [
        (2, "info"),
        (3, "warning"),
        (4, "critical"),
    ],
)
def test_consecutive_budget_overspend_rule_matches_phase_one_thresholds(db_session, months, expected_severity):
    user = _create_user(
        db_session,
        name=f"Consecutive Overspend {expected_severity.title()} User",
        email=f"consecutive-overspend-{expected_severity}@example.com",
    )
    income = _create_category(db_session, user_id=user.user_id, name="Sales", category_type="income")
    marketing = _create_category(db_session, user_id=user.user_id, name="Marketing", category_type="expense")

    budget_months = [date(2026, month_number, 1) for month_number in range(1, months + 1)]
    _add_budgets(
        db_session,
        *[
            Budget(
                user_id=user.user_id,
                category_id=marketing.category_id,
                amount=100.0,
                month=month_start,
                note=f"{month_start.isoformat()} marketing",
            )
            for month_start in budget_months
        ],
    )
    _add_transactions(
        db_session,
        Transaction(
            user_id=user.user_id,
            category_id=income.category_id,
            amount=1000.0,
            type="income",
            description="Current revenue",
            date=date(2026, months, 5),
        ),
        *[
            Transaction(
                user_id=user.user_id,
                category_id=marketing.category_id,
                amount=150.0,
                type="expense",
                description=f"Overspend for {month_start.isoformat()}",
                date=month_start.replace(day=10),
            )
            for month_start in budget_months
        ],
    )

    created = run_rules_for_user(db_session, user.user_id, date(2026, months, 1), date(2026, months, 28))

    consecutive_overspend = next(insight for insight in created if insight.rule_id == "consecutive_budget_overspend")
    assert consecutive_overspend.severity == expected_severity
    assert consecutive_overspend.metadata_json is not None
    assert consecutive_overspend.metadata_json["consecutive_overspend_count"] == months


def test_negative_balance_below_rule_triggers_for_large_deficit(db_session):
    user = User(name="Deficit User", email="deficit@example.com", password_hash="x")
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
                description="Revenue",
                date=date(2026, 4, 3),
            ),
            Transaction(
                user_id=user.user_id,
                category_id=expense.category_id,
                amount=1700.0,
                type="expense",
                description="Large expense",
                date=date(2026, 4, 9),
            ),
        ]
    )
    db_session.commit()

    created = run_rules_for_user(
        db_session,
        user.user_id,
        date(2026, 4, 1),
        date(2026, 4, 30),
    )

    created_rule_ids = {insight.rule_id for insight in created}
    assert "negative_balance" in created_rule_ids
    assert "negative_balance_below" in created_rule_ids


def test_negative_balance_rule_triggers_without_severe_threshold(db_session):
    user = User(name="Moderate Deficit User", email="moderate-deficit@example.com", password_hash="x")
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
                description="Revenue",
                date=date(2026, 4, 3),
            ),
            Transaction(
                user_id=user.user_id,
                category_id=expense.category_id,
                amount=1200.0,
                type="expense",
                description="Moderate expense",
                date=date(2026, 4, 9),
            ),
        ]
    )
    db_session.commit()

    created = run_rules_for_user(
        db_session,
        user.user_id,
        date(2026, 4, 1),
        date(2026, 4, 30),
    )

    negative_balance = next(insight for insight in created if insight.rule_id == "negative_balance")
    assert negative_balance.severity == "warning"
    assert negative_balance.metadata_json is not None
    assert negative_balance.metadata_json["balance_amount"] == -200.0
    assert all(insight.rule_id != "negative_balance_below" for insight in created)


def test_malformed_message_template_does_not_crash_insight_generation(db_session, tmp_path, monkeypatch):
    user = _create_user(db_session, name="Malformed Template User", email="malformed-template@example.com")
    income = _create_category(db_session, user_id=user.user_id, name="Sales", category_type="income")
    expense = _create_category(db_session, user_id=user.user_id, name="Operations", category_type="expense")

    _add_transactions(
        db_session,
        Transaction(
            user_id=user.user_id,
            category_id=income.category_id,
            amount=1000.0,
            type="income",
            description="Revenue",
            date=date(2026, 4, 5),
        ),
        Transaction(
            user_id=user.user_id,
            category_id=expense.category_id,
            amount=900.0,
            type="expense",
            description="Spend",
            date=date(2026, 4, 6),
        ),
    )

    rules_path = tmp_path / "rules.yaml"
    rules_path.write_text(
        """
version: 1
defaults:
  currency: USD
  min_income_for_ratio_rules: 0.0
rules:
  - id: expense_ratio
    type: expense_ratio
    enabled: true
    scope: period
    severity_thresholds:
      warning: 0.85
    titles:
      warning: "High expense ratio detected"
    message_template: "Broken placeholder {missing_value}"
""".strip(),
        encoding="utf-8",
    )

    monkeypatch.setattr(rules_module, "RULES_PATH", rules_path)
    rules_module.clear_rules_cache()

    try:
        created = run_rules_for_user(db_session, user.user_id, date(2026, 4, 1), date(2026, 4, 30))
    finally:
        rules_module.clear_rules_cache()

    expense_ratio_insight = next(insight for insight in created if insight.rule_id == "expense_ratio")
    assert expense_ratio_insight.message == "Broken placeholder {missing_value}"


def test_category_period_scope_keys_are_stable_and_persisted_across_reruns(db_session):
    user = _create_user(db_session, name="Stable Scope Key User", email="stable-scope-keys@example.com")
    income = _create_category(db_session, user_id=user.user_id, name="Sales", category_type="income")
    marketing = _create_category(db_session, user_id=user.user_id, name="Marketing", category_type="expense")
    travel = _create_category(db_session, user_id=user.user_id, name="Travel", category_type="expense")

    _add_budgets(
        db_session,
        Budget(
            user_id=user.user_id,
            category_id=marketing.category_id,
            amount=100.0,
            month=date(2026, 3, 1),
            note="March marketing",
        ),
        Budget(
            user_id=user.user_id,
            category_id=marketing.category_id,
            amount=100.0,
            month=date(2026, 4, 1),
            note="April marketing",
        ),
    )
    _add_transactions(
        db_session,
        Transaction(
            user_id=user.user_id,
            category_id=income.category_id,
            amount=1000.0,
            type="income",
            description="April revenue",
            date=date(2026, 4, 5),
        ),
        Transaction(
            user_id=user.user_id,
            category_id=marketing.category_id,
            amount=150.0,
            type="expense",
            description="March overspend",
            date=date(2026, 3, 10),
        ),
        Transaction(
            user_id=user.user_id,
            category_id=marketing.category_id,
            amount=150.0,
            type="expense",
            description="April overspend",
            date=date(2026, 4, 10),
        ),
        Transaction(
            user_id=user.user_id,
            category_id=travel.category_id,
            amount=600.0,
            type="expense",
            description="April travel",
            date=date(2026, 4, 12),
        ),
    )

    created = run_rules_for_user(db_session, user.user_id, date(2026, 4, 1), date(2026, 4, 30))
    category_period_rule_ids = {
        "budget_overspend_ratio",
        "category_income_ratio",
        "consecutive_budget_overspend",
        "missing_budget_high_spend",
    }
    first_scope_keys = {
        (insight.rule_id, (insight.metadata_json or {}).get("scope_key"))
        for insight in created
        if insight.rule_id in category_period_rule_ids
    }

    rerun = run_rules_for_user(db_session, user.user_id, date(2026, 4, 1), date(2026, 4, 30))
    stored = (
        db_session.query(AIInsight)
        .filter(
            AIInsight.user_id == user.user_id,
            AIInsight.period_start == date(2026, 4, 1),
            AIInsight.period_end == date(2026, 4, 30),
            AIInsight.rule_id.in_(category_period_rule_ids),
        )
        .all()
    )
    stored_scope_keys = {
        (insight.rule_id, (insight.metadata_json or {}).get("scope_key"))
        for insight in stored
    }

    assert first_scope_keys
    assert rerun == []
    assert stored_scope_keys == first_scope_keys


def test_category_period_rules_always_include_scope_key_metadata(db_session):
    user = _create_user(db_session, name="Category Scope Metadata User", email="category-scope-metadata@example.com")
    income = _create_category(db_session, user_id=user.user_id, name="Sales", category_type="income")
    marketing = _create_category(db_session, user_id=user.user_id, name="Marketing", category_type="expense")
    travel = _create_category(db_session, user_id=user.user_id, name="Travel", category_type="expense")

    _add_budgets(
        db_session,
        Budget(
            user_id=user.user_id,
            category_id=marketing.category_id,
            amount=100.0,
            month=date(2026, 3, 1),
            note="March marketing",
        ),
        Budget(
            user_id=user.user_id,
            category_id=marketing.category_id,
            amount=100.0,
            month=date(2026, 4, 1),
            note="April marketing",
        ),
    )
    _add_transactions(
        db_session,
        Transaction(
            user_id=user.user_id,
            category_id=income.category_id,
            amount=1000.0,
            type="income",
            description="April revenue",
            date=date(2026, 4, 5),
        ),
        Transaction(
            user_id=user.user_id,
            category_id=marketing.category_id,
            amount=150.0,
            type="expense",
            description="March overspend",
            date=date(2026, 3, 10),
        ),
        Transaction(
            user_id=user.user_id,
            category_id=marketing.category_id,
            amount=150.0,
            type="expense",
            description="April overspend",
            date=date(2026, 4, 10),
        ),
        Transaction(
            user_id=user.user_id,
            category_id=travel.category_id,
            amount=600.0,
            type="expense",
            description="April travel",
            date=date(2026, 4, 12),
        ),
    )

    created = run_rules_for_user(db_session, user.user_id, date(2026, 4, 1), date(2026, 4, 30))
    category_period_rule_ids = {
        "budget_overspend_ratio",
        "category_income_ratio",
        "consecutive_budget_overspend",
        "missing_budget_high_spend",
    }

    category_period_insights = [insight for insight in created if insight.rule_id in category_period_rule_ids]

    assert category_period_insights
    assert all(insight.metadata_json is not None for insight in category_period_insights)
    assert all((insight.metadata_json or {}).get("scope_key") for insight in category_period_insights)


@pytest.mark.parametrize(
    ("yaml_text", "expected_message"),
    [
        (
            """
version: 1
defaults: {}
rules:
  - id: duplicate_rule
    type: expense_ratio
    severity_thresholds:
      warning: 0.8
  - id: duplicate_rule
    type: income_drop_percent
    severity_thresholds:
      warning: 10
""",
            "Duplicate rule id",
        ),
        (
            """
version: 1
defaults: {}
rules:
  - id: bad_type
    type: definitely_unknown
    severity_thresholds:
      warning: 1
""",
            "Unknown rule type",
        ),
        (
            """
version: 1
defaults: {}
rules:
  - id: bad_severity
    type: expense_ratio
    severity_thresholds:
      urgent: 0.8
""",
            "unsupported severity",
        ),
        (
            """
version: 1
defaults: {}
rules:
  - id: empty_thresholds
    type: expense_ratio
    severity_thresholds: {}
""",
            "non-empty severity_thresholds",
        ),
        (
            """
version: 1
defaults: {}
rules:
  - id: bad_threshold
    type: expense_ratio
    severity_thresholds:
      warning: high
""",
            "must be numeric",
        ),
        (
            """
version: 1
defaults: {}
rules:
  - id: bad_scope
    type: expense_ratio
    scope: monthly
    severity_thresholds:
      warning: 0.8
""",
            "unsupported scope",
        ),
    ],
)
def test_rule_config_validation_fails_fast(tmp_path, monkeypatch, yaml_text, expected_message):
    rules_path = tmp_path / "rules.yaml"
    rules_path.write_text(yaml_text.strip(), encoding="utf-8")
    monkeypatch.setattr(rules_module, "RULES_PATH", rules_path)
    rules_module.clear_rules_cache()

    try:
        with pytest.raises(ValueError, match=expected_message):
            rules_module.load_ruleset()
    finally:
        rules_module.clear_rules_cache()
