from calendar import monthrange
from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.time import utcnow
from app.db.session import get_db
from app.models.category import Category
from app.models.transaction import Transaction
from app.models.user import User
from app.schemas.dashboard import CategoryBreakdownItem, DashboardSummary, MonthlyTrendPoint
from app.services.budget_metrics import list_budget_snapshots, normalize_month

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


def _month_start(value: date) -> date:
    return value.replace(day=1)


def _add_months(value: date, months: int) -> date:
    year = value.year + (value.month - 1 + months) // 12
    month = (value.month - 1 + months) % 12 + 1
    return date(year, month, 1)


def _month_end(value: date) -> date:
    return date(value.year, value.month, monthrange(value.year, value.month)[1])


def _health_status(expense_ratio: float, savings_rate: float, over_budget_count: int) -> tuple[str, str]:
    if over_budget_count > 0 or expense_ratio >= 0.9 or savings_rate < 0:
        return "at_risk", "Spending or budget usage needs attention this month."
    if expense_ratio >= 0.75 or savings_rate < 0.1:
        return "watch", "Your finances are stable, but expenses are close to income."
    return "healthy", "Income is comfortably ahead of expenses."


@router.get("/summary", response_model=DashboardSummary)
def summary(
    month: date | None = Query(default=None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    income = (
        db.query(func.coalesce(func.sum(Transaction.amount), 0.0))
        .filter(Transaction.user_id == current_user.user_id, func.lower(Transaction.type) == "income")
        .scalar()
    )
    expense = (
        db.query(func.coalesce(func.sum(Transaction.amount), 0.0))
        .filter(Transaction.user_id == current_user.user_id, func.lower(Transaction.type) == "expense")
        .scalar()
    )
    count = db.query(func.count(Transaction.transaction_id)).filter(Transaction.user_id == current_user.user_id).scalar()
    total_income = float(income or 0.0)
    total_expense = float(expense or 0.0)
    balance = total_income - total_expense

    category_breakdown = [
        CategoryBreakdownItem(category_name=category_name or "Uncategorized", total=float(total or 0.0))
        for category_name, total in (
            db.query(
                func.coalesce(Category.name, "Uncategorized").label("category_name"),
                func.coalesce(func.sum(Transaction.amount), 0.0).label("total"),
            )
            .outerjoin(
                Category,
                (Category.category_id == Transaction.category_id)
                & (Category.user_id == current_user.user_id),
            )
            .filter(Transaction.user_id == current_user.user_id, func.lower(Transaction.type) == "expense")
            .group_by(func.coalesce(Category.name, "Uncategorized"))
            .order_by(func.coalesce(func.sum(Transaction.amount), 0.0).desc())
            .all()
        )
    ]
    top_expense = category_breakdown[0] if category_breakdown else None

    current_month = _month_start(utcnow().date())
    budget_month = normalize_month(month) if month is not None else current_month
    trend_start = _add_months(current_month, -5)
    trend_end = _month_end(current_month)
    trend_rows = (
        db.query(Transaction.date, Transaction.type, Transaction.amount)
        .filter(
            Transaction.user_id == current_user.user_id,
            Transaction.date >= trend_start,
            Transaction.date <= trend_end,
        )
        .all()
    )
    trend_map = {
        _add_months(trend_start, offset).strftime("%Y-%m"): {"income": 0.0, "expense": 0.0}
        for offset in range(6)
    }
    for tx_date, tx_type, amount in trend_rows:
        key = normalize_month(tx_date).strftime("%Y-%m")
        normalized_type = str(tx_type).lower()
        if key in trend_map and normalized_type in trend_map[key]:
            trend_map[key][normalized_type] += float(amount or 0.0)
    monthly_trend = [
        MonthlyTrendPoint(month=month, income=values["income"], expense=values["expense"])
        for month, values in trend_map.items()
    ]
    active_months = [item for item in monthly_trend if item.income or item.expense]
    average_month_count = max(len(active_months), 1)

    budget_snapshots = list_budget_snapshots(db, user_id=current_user.user_id, month=budget_month)
    budget_total = sum(float(item["amount"] or 0.0) for item in budget_snapshots)
    budget_spent = sum(float(item["spent"] or 0.0) for item in budget_snapshots)
    budget_remaining = budget_total - budget_spent
    over_budget_count = sum(1 for item in budget_snapshots if item["status"] == "over")

    expense_ratio = total_expense / total_income if total_income > 0 else 0.0
    savings_rate = balance / total_income if total_income > 0 else 0.0
    health_status, focus_message = _health_status(expense_ratio, savings_rate, over_budget_count)

    return DashboardSummary(
        total_income=total_income,
        total_expense=total_expense,
        balance=balance,
        expense_ratio=expense_ratio,
        savings_rate=savings_rate,
        monthly_average_income=total_income / average_month_count,
        monthly_average_expense=total_expense / average_month_count,
        transaction_count=int(count or 0),
        budget_total=budget_total,
        budget_spent=budget_spent,
        budget_remaining=budget_remaining,
        over_budget_count=over_budget_count,
        budget_month=budget_month.strftime("%Y-%m"),
        top_expense_category_name=top_expense.category_name if top_expense else None,
        top_expense_category_total=top_expense.total if top_expense else 0.0,
        health_status=health_status,
        focus_message=focus_message,
        monthly_trend=monthly_trend,
        category_breakdown=category_breakdown,
    )
