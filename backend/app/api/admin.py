from collections import Counter
from datetime import date, timedelta
from typing import Callable, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import case, func, or_
from sqlalchemy.orm import Session

from app.api.deps import require_admin
from app.core.time import utcnow
from app.db.session import get_db
from app.models.admin import Admin
from app.models.ai_insight import AIInsight
from app.models.budget import Budget
from app.models.category import Category
from app.models.system_log import SystemLog
from app.models.transaction import Transaction
from app.models.user import User
from app.schemas.admin_panel import (
    AdminActiveUser,
    AdminBudgetRow,
    AdminAnalyticsBudgetsOut,
    AdminAnalyticsInsightsOut,
    AdminAnalyticsOverviewOut,
    AdminAnalyticsTransactionsOut,
    AdminAnalyticsUsersOut,
    AdminBudgetsResponse,
    AdminBudgetTrend,
    AdminCategoriesResponse,
    AdminCategorySummary,
    AdminCategoryOut,
    AdminCountByLabel,
    AdminDashboardOut,
    AdminDefaultCategoriesResult,
    AdminDefaultCategoryOut,
    AdminInsightOut,
    AdminInsightsResponse,
    AdminLogRow,
    AdminLogsResponse,
    AdminLogSummary,
    AdminOverspendingAnalysis,
    AdminOverspendingCategory,
    AdminPopularCategory,
    AdminSpendDistributionItem,
    AdminTransactionsResponse,
    AdminTransactionSummary,
    AdminTransactionOut,
    AdminTransactionTrend,
    AdminUserFinancialSummary,
    AdminUserOverview,
    AdminUserRow,
    AdminUserSummary,
    AdminUsersResponse,
    AdminUserStatusUpdate,
)
from app.schemas.user import UserOut
from app.services.admin_analytics import (
    get_admin_analytics_budgets,
    get_admin_analytics_insights,
    get_admin_analytics_overview,
    get_admin_analytics_transactions,
    get_admin_analytics_users,
    get_admin_dashboard_data,
    invalidate_admin_analytics_cache,
)
from app.services.budget_metrics import list_budget_snapshots
from app.services.fraud_insights import transaction_fraud_statuses
from app.services.system_log import log_system_event

router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(require_admin)])

DEFAULT_CATEGORIES: list[tuple[str, str]] = [
    ("Sales", "income"),
    ("Salary", "income"),
    ("Office Supplies", "expense"),
    ("Rent", "expense"),
    ("Marketing", "expense"),
    ("Utilities", "expense"),
]


def datetime_for_date(value: date):
    return utcnow().replace(year=value.year, month=value.month, day=value.day, hour=0, minute=0, second=0, microsecond=0)


def next_datetime_for_date(value: date):
    return datetime_for_date(value) + timedelta(days=1)


def _normalize_text_search(value: str | None) -> str | None:
    normalized = (value or "").strip().lower()
    return normalized or None


def _search_pattern(value: str | None) -> str | None:
    normalized = _normalize_text_search(value)
    return f"%{normalized}%" if normalized else None


def _apply_pagination(items: list, limit: int, offset: int) -> list:
    return items[offset : offset + limit]


def _sort_value(value):
    if value is None:
        return (1, "")
    if isinstance(value, str):
        return (0, value.lower())
    return (0, value)


def _validate_sort_by(sort_by: str, allowed_sort_fields: set[str]) -> None:
    if sort_by not in allowed_sort_fields:
        allowed = ", ".join(sorted(allowed_sort_fields))
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Unsupported sort_by '{sort_by}'. Allowed values: {allowed}",
        )


def _order_query(query, sort_by: str, sort_order: str, sort_columns: dict[str, object], tie_breaker):
    order_column = sort_columns[sort_by]
    return query.order_by(
        order_column.asc() if sort_order == "asc" else order_column.desc(),
        tie_breaker.asc() if sort_order == "asc" else tie_breaker.desc(),
    )


def _sort_rows(items: list[dict], sort_by: str, sort_order: str, value_getters: dict[str, Callable[[dict], object]]) -> list[dict]:
    getter = value_getters.get(sort_by)
    if getter is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Unsupported sort_by '{sort_by}'",
        )
    return sorted(items, key=lambda item: _sort_value(getter(item)), reverse=sort_order == "desc")


def _get_user_or_404(db: Session, user_id: int) -> User:
    user = db.query(User).filter(User.user_id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user


def _user_metric_map(db: Session, model, id_column, user_id: int | None = None) -> dict[int, dict[str, object]]:
    query = db.query(
        model.user_id,
        func.count(id_column),
        func.max(model.created_at),
    )
    if user_id is not None:
        query = query.filter(model.user_id == user_id)
    rows = query.group_by(model.user_id).all()
    return {
        user_id: {"count": int(count or 0), "last": last_created_at}
        for user_id, count, last_created_at in rows
    }


def _user_stat_maps(db: Session, user_id: int | None = None):
    tx_map = _user_metric_map(db, Transaction, Transaction.transaction_id, user_id=user_id)
    category_map = _user_metric_map(db, Category, Category.category_id, user_id=user_id)
    budget_map = _user_metric_map(db, Budget, Budget.budget_id, user_id=user_id)
    insight_map = _user_metric_map(db, AIInsight, AIInsight.insight_id, user_id=user_id)
    return tx_map, category_map, budget_map, insight_map


def _build_admin_user_row(db: Session, user: User) -> AdminUserRow:
    tx_map, category_map, budget_map, insight_map = _user_stat_maps(db, user_id=user.user_id)
    tx_stats = tx_map.get(user.user_id, {"count": 0, "last": None})
    category_stats = category_map.get(user.user_id, {"count": 0, "last": None})
    budget_stats = budget_map.get(user.user_id, {"count": 0, "last": None})
    insight_stats = insight_map.get(user.user_id, {"count": 0, "last": None})
    last_activity = max(
        (
            value
            for value in [
                user.created_at,
                tx_stats["last"],
                category_stats["last"],
                budget_stats["last"],
                insight_stats["last"],
            ]
            if value is not None
        ),
        default=None,
    )
    return AdminUserRow.model_validate(
        {
            "user_id": user.user_id,
            "name": user.name,
            "email": user.email,
            "is_active": user.is_active,
            "created_at": user.created_at,
            "transactions_count": int(tx_stats["count"]),
            "categories_count": int(category_stats["count"]),
            "budgets_count": int(budget_stats["count"]),
            "insights_count": int(insight_stats["count"]),
            "last_activity": last_activity,
        }
    )


def _serialize_logs(rows) -> list[AdminLogRow]:
    logs: list[AdminLogRow] = []
    for log, admin_name, admin_email, user_name, user_email in rows:
        logs.append(
            AdminLogRow(
                log_id=log.log_id,
                event_type=log.event_type,
                level=log.level,
                message=log.message,
                created_at=log.created_at,
                metadata=log.metadata_json,
                admin_id=log.admin_id,
                admin_name=admin_name,
                admin_email=admin_email,
                user_id=log.user_id,
                user_name=user_name,
                user_email=user_email,
            )
        )
    return logs


def _logs_query(db: Session):
    return (
        db.query(SystemLog, Admin.name, Admin.email, User.name, User.email)
        .outerjoin(Admin, Admin.admin_id == SystemLog.admin_id)
        .outerjoin(User, User.user_id == SystemLog.user_id)
    )


@router.get("/dashboard", response_model=AdminDashboardOut)
def get_admin_dashboard(
    days: int = Query(default=30, ge=7, le=180),
    user_id: int | None = Query(default=None),
    db: Session = Depends(get_db),
):
    if user_id is not None:
        _get_user_or_404(db, user_id)
    return get_admin_dashboard_data(db, user_id=user_id, days=days)


@router.get("/analytics/overview", response_model=AdminAnalyticsOverviewOut)
def get_admin_analytics_overview_endpoint(
    days: int = Query(default=30, ge=7, le=180),
    user_id: int | None = Query(default=None),
    db: Session = Depends(get_db),
):
    if user_id is not None:
        _get_user_or_404(db, user_id)
    return get_admin_analytics_overview(db, user_id=user_id, days=days)


@router.get("/analytics/transactions", response_model=AdminAnalyticsTransactionsOut)
def get_admin_analytics_transactions_endpoint(
    days: int = Query(default=30, ge=7, le=180),
    user_id: int | None = Query(default=None),
    db: Session = Depends(get_db),
):
    if user_id is not None:
        _get_user_or_404(db, user_id)
    return get_admin_analytics_transactions(db, user_id=user_id, days=days)


@router.get("/analytics/users", response_model=AdminAnalyticsUsersOut)
def get_admin_analytics_users_endpoint(
    user_id: int | None = Query(default=None),
    db: Session = Depends(get_db),
):
    if user_id is not None:
        _get_user_or_404(db, user_id)
    return get_admin_analytics_users(db, user_id=user_id)


@router.get("/analytics/insights", response_model=AdminAnalyticsInsightsOut)
def get_admin_analytics_insights_endpoint(
    user_id: int | None = Query(default=None),
    db: Session = Depends(get_db),
):
    if user_id is not None:
        _get_user_or_404(db, user_id)
    return get_admin_analytics_insights(db, user_id=user_id)


@router.get("/analytics/budgets", response_model=AdminAnalyticsBudgetsOut)
def get_admin_analytics_budgets_endpoint(
    user_id: int | None = Query(default=None),
    db: Session = Depends(get_db),
):
    if user_id is not None:
        _get_user_or_404(db, user_id)
    return get_admin_analytics_budgets(db, user_id=user_id)


@router.get("/users", response_model=AdminUsersResponse)
def list_users(
    search: str | None = Query(default=None),
    is_active: bool | None = Query(default=None),
    limit: int = Query(default=10, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    sort_by: str = Query(default="created_at"),
    sort_order: Literal["asc", "desc"] = Query(default="desc"),
    db: Session = Depends(get_db),
):
    sort_columns = {
        "name": func.lower(User.name),
        "email": func.lower(User.email),
        "created_at": User.created_at,
        "is_active": User.is_active,
    }
    row_sort_getters = {
        "transactions_count": lambda item: item["transactions_count"],
        "categories_count": lambda item: item["categories_count"],
        "budgets_count": lambda item: item["budgets_count"],
        "insights_count": lambda item: item["insights_count"],
        "last_activity": lambda item: item["last_activity"],
    }
    _validate_sort_by(sort_by, set(sort_columns) | set(row_sort_getters))

    query = db.query(User)
    pattern = _search_pattern(search)
    if pattern:
        query = query.filter(
            or_(func.lower(User.name).like(pattern), func.lower(User.email).like(pattern))
        )
    if is_active is not None:
        query = query.filter(User.is_active == is_active)

    if sort_by in sort_columns:
        users = _order_query(query, sort_by, sort_order, sort_columns, User.user_id).all()
    else:
        users = query.order_by(User.created_at.desc(), User.user_id.desc()).all()
    tx_map, category_map, budget_map, insight_map = _user_stat_maps(db)

    rows = []
    for user in users:
        tx_stats = tx_map.get(user.user_id, {"count": 0, "last": None})
        category_stats = category_map.get(user.user_id, {"count": 0, "last": None})
        budget_stats = budget_map.get(user.user_id, {"count": 0, "last": None})
        insight_stats = insight_map.get(user.user_id, {"count": 0, "last": None})
        candidates = [
            user.created_at,
            tx_stats["last"],
            category_stats["last"],
            budget_stats["last"],
            insight_stats["last"],
        ]
        last_activity = max((value for value in candidates if value is not None), default=None)
        rows.append(
            {
                "user_id": user.user_id,
                "name": user.name,
                "email": user.email,
                "is_active": user.is_active,
                "created_at": user.created_at,
                "transactions_count": int(tx_stats["count"]),
                "categories_count": int(category_stats["count"]),
                "budgets_count": int(budget_stats["count"]),
                "insights_count": int(insight_stats["count"]),
                "last_activity": last_activity,
            }
        )

    if sort_by in row_sort_getters:
        rows = _sort_rows(rows, sort_by, sort_order, row_sort_getters)
    total = len(rows)
    page_rows = [AdminUserRow.model_validate(row) for row in _apply_pagination(rows, limit, offset)]
    active_count = sum(1 for row in rows if row["is_active"])
    return AdminUsersResponse(
        total=total,
        limit=limit,
        offset=offset,
        sort_by=sort_by,
        sort_order=sort_order,
        users=page_rows,
        summary=AdminUserSummary(
            active_count=active_count,
            inactive_count=total - active_count,
        ),
    )


@router.get("/users/{user_id}/overview", response_model=AdminUserOverview)
def get_user_overview(
    user_id: int,
    db: Session = Depends(get_db),
):
    user = _get_user_or_404(db, user_id)
    total_income = (
        db.query(func.coalesce(func.sum(Transaction.amount), 0.0))
        .filter(Transaction.user_id == user_id, Transaction.type == "income")
        .scalar()
    )
    total_expense = (
        db.query(func.coalesce(func.sum(Transaction.amount), 0.0))
        .filter(Transaction.user_id == user_id, Transaction.type == "expense")
        .scalar()
    )
    budget_snapshots = list_budget_snapshots(db, user_id=user_id)
    recent_logs = _serialize_logs(
        _logs_query(db)
        .filter(SystemLog.user_id == user_id)
        .order_by(SystemLog.created_at.desc(), SystemLog.log_id.desc())
        .limit(8)
        .all()
    )

    recent_insights = [
        AdminInsightOut(
            insight_id=insight.insight_id,
            user_id=insight.user_id,
            user_name=user.name,
            user_email=user.email,
            title=insight.title,
            message=insight.message,
            severity=insight.severity,
            period_start=insight.period_start,
            period_end=insight.period_end,
            created_at=insight.created_at,
        )
        for insight in (
            db.query(AIInsight)
            .filter(AIInsight.user_id == user_id)
            .order_by(AIInsight.created_at.desc(), AIInsight.insight_id.desc())
            .limit(5)
            .all()
        )
    ]

    income = float(total_income or 0.0)
    expense = float(total_expense or 0.0)
    return AdminUserOverview(
        user=_build_admin_user_row(db, user),
        financial_summary=AdminUserFinancialSummary(
            total_income=income,
            total_expense=expense,
            balance=income - expense,
            over_budget_count=sum(1 for snapshot in budget_snapshots if snapshot["status"] == "over"),
        ),
        recent_logs=recent_logs,
        recent_insights=recent_insights,
    )


@router.delete("/users/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_user(
    user_id: int,
    db: Session = Depends(get_db),
    current_admin: Admin = Depends(require_admin),
):
    user = db.query(User).filter(User.user_id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    email = user.email
    log_system_event(
        db,
        "delete_user",
        f"Admin deleted user {email}",
        level="warning",
        admin_id=current_admin.admin_id,
        user_id=user.user_id,
        entity_id=user.user_id,
        metadata={
            "email": email,
            "is_active": user.is_active,
        },
    )
    db.delete(user)
    db.commit()
    invalidate_admin_analytics_cache()
    return None


@router.patch("/users/{user_id}/status", response_model=UserOut)
def update_user_status(
    user_id: int,
    payload: AdminUserStatusUpdate,
    db: Session = Depends(get_db),
    current_admin: Admin = Depends(require_admin),
):
    user = db.query(User).filter(User.user_id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    user.is_active = payload.is_active
    action = "enable_user" if payload.is_active else "disable_user"
    log_system_event(
        db,
        action,
        f"Admin {'enabled' if payload.is_active else 'disabled'} user {user.email}",
        level="info" if payload.is_active else "warning",
        admin_id=current_admin.admin_id,
        user_id=user.user_id,
        entity_id=user.user_id,
        metadata={
            "email": user.email,
            "is_active": payload.is_active,
        },
    )
    db.commit()
    invalidate_admin_analytics_cache()
    db.refresh(user)
    return user


@router.get("/transactions", response_model=AdminTransactionsResponse)
def list_admin_transactions(
    search: str | None = Query(default=None),
    user_id: int | None = Query(default=None),
    category_id: int | None = Query(default=None),
    transaction_type: Literal["income", "expense"] | None = Query(default=None, alias="type"),
    date_from: date | None = Query(default=None),
    date_to: date | None = Query(default=None),
    limit: int = Query(default=10, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    sort_by: str = Query(default="date"),
    sort_order: Literal["asc", "desc"] = Query(default="desc"),
    db: Session = Depends(get_db),
):
    query = (
        db.query(Transaction, User.name, User.email, Category.name)
        .join(User, User.user_id == Transaction.user_id)
        .join(Category, Category.category_id == Transaction.category_id)
    )
    pattern = _search_pattern(search)
    if pattern:
        query = query.filter(
            or_(
                func.lower(func.coalesce(Transaction.description, "")).like(pattern),
                func.lower(User.name).like(pattern),
                func.lower(User.email).like(pattern),
                func.lower(Category.name).like(pattern),
            )
        )
    if user_id is not None:
        query = query.filter(Transaction.user_id == user_id)
    if category_id is not None:
        query = query.filter(Transaction.category_id == category_id)
    if transaction_type is not None:
        query = query.filter(Transaction.type == transaction_type)
    if date_from is not None:
        query = query.filter(Transaction.date >= date_from)
    if date_to is not None:
        query = query.filter(Transaction.date <= date_to)

    total = query.order_by(None).count()
    summary_amount, income_count, expense_count = query.order_by(None).with_entities(
        func.coalesce(func.sum(Transaction.amount), 0.0),
        func.coalesce(func.sum(case((Transaction.type == "income", 1), else_=0)), 0),
        func.coalesce(func.sum(case((Transaction.type == "expense", 1), else_=0)), 0),
    ).one()

    sort_columns = {
        "date": Transaction.date,
        "created_at": Transaction.created_at,
        "amount": Transaction.amount,
        "type": Transaction.type,
        "user_name": User.name,
        "user_email": User.email,
        "category_name": Category.name,
        "description": Transaction.description,
    }
    order_column = sort_columns.get(sort_by, Transaction.date)
    ordered_query = query.order_by(
        order_column.asc() if sort_order == "asc" else order_column.desc(),
        Transaction.transaction_id.asc() if sort_order == "asc" else Transaction.transaction_id.desc(),
    )

    page_rows = ordered_query.offset(offset).limit(limit).all()
    fraud_statuses = transaction_fraud_statuses(
        db,
        transaction_ids={int(transaction.transaction_id) for transaction, *_ in page_rows},
    )

    rows = []
    for transaction, user_name, user_email, category_name in page_rows:
        fraud_status = fraud_statuses.get(int(transaction.transaction_id), {})
        rows.append(
            AdminTransactionOut.model_validate(
                {
                    "transaction_id": transaction.transaction_id,
                    "user_id": transaction.user_id,
                    "user_name": user_name,
                    "user_email": user_email,
                    "category_id": transaction.category_id,
                    "category_name": category_name,
                    "amount": float(transaction.amount),
                    "type": transaction.type,
                    "description": transaction.description,
                    "date": transaction.date,
                    "created_at": transaction.created_at,
                    "fraud_risk_level": fraud_status.get("fraud_risk_level"),
                    "fraud_probability": fraud_status.get("fraud_probability"),
                    "fraud_insight_id": fraud_status.get("fraud_insight_id"),
                }
            )
        )
    return AdminTransactionsResponse(
        total=total,
        limit=limit,
        offset=offset,
        sort_by=sort_by,
        sort_order=sort_order,
        transactions=rows,
        summary=AdminTransactionSummary(
            total_amount=float(summary_amount or 0.0),
            income_count=int(income_count or 0),
            expense_count=int(expense_count or 0),
        ),
    )


@router.get("/categories", response_model=AdminCategoriesResponse)
def list_admin_categories(
    user_id: int | None = Query(default=None),
    search: str | None = Query(default=None),
    category_type: Literal["income", "expense", "both"] | None = Query(default=None, alias="type"),
    limit: int = Query(default=10, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    sort_by: str = Query(default="created_at"),
    sort_order: Literal["asc", "desc"] = Query(default="desc"),
    db: Session = Depends(get_db),
):
    sort_columns = {
        "name": func.lower(Category.name),
        "created_at": Category.created_at,
        "type": Category.type,
        "user_name": func.lower(User.name),
        "user_email": func.lower(User.email),
    }
    row_sort_getters = {
        "transactions_count": lambda item: item["transactions_count"],
        "budgets_count": lambda item: item["budgets_count"],
    }
    _validate_sort_by(sort_by, set(sort_columns) | set(row_sort_getters))

    tx_count_rows = (
        db.query(Transaction.category_id, func.count(Transaction.transaction_id))
        .group_by(Transaction.category_id)
        .all()
    )
    tx_count_map = {category_id: int(count or 0) for category_id, count in tx_count_rows}
    budget_count_rows = (
        db.query(Budget.category_id, func.count(Budget.budget_id))
        .group_by(Budget.category_id)
        .all()
    )
    budget_count_map = {category_id: int(count or 0) for category_id, count in budget_count_rows}

    query = db.query(Category, User.name, User.email).join(User, User.user_id == Category.user_id)
    if user_id is not None:
        query = query.filter(Category.user_id == user_id)
    if category_type is not None:
        query = query.filter(Category.type == category_type)
    pattern = _search_pattern(search)
    if pattern:
        query = query.filter(
            or_(
                func.lower(Category.name).like(pattern),
                func.lower(User.name).like(pattern),
                func.lower(User.email).like(pattern),
            )
        )

    if sort_by in sort_columns:
        query = _order_query(query, sort_by, sort_order, sort_columns, Category.category_id)
    else:
        query = query.order_by(Category.created_at.desc(), Category.category_id.desc())

    rows = []
    for category, user_name, user_email in query.all():
        rows.append(
            {
                "category_id": category.category_id,
                "user_id": category.user_id,
                "user_name": user_name,
                "user_email": user_email,
                "name": category.name,
                "type": category.type,
                "transactions_count": tx_count_map.get(category.category_id, 0),
                "budgets_count": budget_count_map.get(category.category_id, 0),
                "created_at": category.created_at,
            }
        )
    if sort_by in row_sort_getters:
        rows = _sort_rows(rows, sort_by, sort_order, row_sort_getters)
    total = len(rows)
    return AdminCategoriesResponse(
        total=total,
        limit=limit,
        offset=offset,
        sort_by=sort_by,
        sort_order=sort_order,
        categories=[AdminCategoryOut.model_validate(row) for row in _apply_pagination(rows, limit, offset)],
        summary=AdminCategorySummary(
            income_count=sum(1 for row in rows if row["type"] == "income"),
            expense_count=sum(1 for row in rows if row["type"] == "expense"),
            both_count=sum(1 for row in rows if row["type"] == "both"),
        ),
    )


@router.delete("/categories/{category_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_admin_category(
    category_id: int,
    db: Session = Depends(get_db),
    current_admin: Admin = Depends(require_admin),
):
    category = db.query(Category).filter(Category.category_id == category_id).first()
    if not category:
        raise HTTPException(status_code=404, detail="Category not found")

    budgets_deleted = db.query(Budget).filter(Budget.category_id == category_id).count()
    transactions_deleted = db.query(Transaction).filter(Transaction.category_id == category_id).count()
    log_system_event(
        db,
        "delete_category",
        f"Admin deleted category '{category.name}'",
        level="warning",
        admin_id=current_admin.admin_id,
        user_id=category.user_id,
        entity_id=category.category_id,
        metadata={
            "category_name": category.name,
            "category_type": category.type,
            "budgets_deleted": budgets_deleted,
            "transactions_deleted": transactions_deleted,
            "source": "admin_categories",
        },
    )
    db.query(Budget).filter(Budget.category_id == category_id).delete(synchronize_session=False)
    db.query(Transaction).filter(Transaction.category_id == category_id).delete(synchronize_session=False)
    db.delete(category)
    db.commit()
    invalidate_admin_analytics_cache()
    return None


@router.post("/categories/defaults", response_model=AdminDefaultCategoriesResult)
def create_default_categories(
    user_id: int | None = Query(default=None),
    db: Session = Depends(get_db),
    current_admin: Admin = Depends(require_admin),
):
    users_query = db.query(User)
    if user_id is not None:
        users_query = users_query.filter(User.user_id == user_id)
    users = users_query.order_by(User.user_id.asc()).all()
    if user_id is not None and not users:
        raise HTTPException(status_code=404, detail="User not found")

    created: list[AdminDefaultCategoryOut] = []
    for user in users:
        existing_names = {
            name.lower()
            for (name,) in db.query(Category.name).filter(Category.user_id == user.user_id).all()
        }
        for name, category_type in DEFAULT_CATEGORIES:
            if name.lower() in existing_names:
                continue
            category = Category(user_id=user.user_id, name=name, type=category_type)
            db.add(category)
            db.flush()
            log_system_event(
                db,
                "create_category",
                f"Admin created default category '{category.name}' for {user.email}",
                admin_id=current_admin.admin_id,
                user_id=user.user_id,
                entity_id=category.category_id,
                metadata={
                    "category_name": category.name,
                    "category_type": category.type,
                    "source": "admin_defaults",
                },
            )
            created.append(
                AdminDefaultCategoryOut(
                    user_id=user.user_id,
                    category_id=category.category_id,
                    name=category.name,
                    type=category.type,
                )
            )
            existing_names.add(name.lower())

    db.commit()
    invalidate_admin_analytics_cache()
    return AdminDefaultCategoriesResult(
        target_user_count=len(users),
        created_count=len(created),
        created=created,
    )


@router.get("/budgets", response_model=AdminBudgetsResponse)
def list_admin_budgets(
    user_id: int | None = Query(default=None),
    month: date | None = Query(default=None),
    search: str | None = Query(default=None),
    limit: int = Query(default=10, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    sort_by: str = Query(default="month"),
    sort_order: Literal["asc", "desc"] = Query(default="desc"),
    db: Session = Depends(get_db),
):
    snapshots = list_budget_snapshots(db, user_id=user_id, month=month)
    normalized_search = _normalize_text_search(search)
    if normalized_search:
        snapshots = [
            item
            for item in snapshots
            if normalized_search in str(item["category_name"]).lower()
            or normalized_search in str(item["user_name"]).lower()
            or normalized_search in str(item["user_email"]).lower()
            or normalized_search in str(item["note"] or "").lower()
        ]

    budget_rows = [AdminBudgetRow.model_validate(item) for item in snapshots]

    total_budgeted = sum(item.amount for item in budget_rows)
    total_spent = sum(item.spent for item in budget_rows)
    total_overspent = sum(max(item.spent - item.amount, 0.0) for item in budget_rows)
    over_budget_count = sum(1 for item in budget_rows if item.status == "over")
    near_limit_count = sum(1 for item in budget_rows if item.status == "near_limit")

    popular_map: dict[str, dict[str, float | int]] = {}
    trend_map: dict[str, dict[str, float | int]] = {}
    for item in budget_rows:
        popular_entry = popular_map.setdefault(
            item.category_name,
            {"category_name": item.category_name, "budget_count": 0, "total_budgeted": 0.0, "total_spent": 0.0},
        )
        popular_entry["budget_count"] = int(popular_entry["budget_count"]) + 1
        popular_entry["total_budgeted"] = float(popular_entry["total_budgeted"]) + item.amount
        popular_entry["total_spent"] = float(popular_entry["total_spent"]) + item.spent

        month_key = item.month.strftime("%Y-%m")
        trend_entry = trend_map.setdefault(
            month_key,
            {"month": month_key, "budgets_count": 0, "total_budgeted": 0.0, "total_spent": 0.0, "over_budget_count": 0},
        )
        trend_entry["budgets_count"] = int(trend_entry["budgets_count"]) + 1
        trend_entry["total_budgeted"] = float(trend_entry["total_budgeted"]) + item.amount
        trend_entry["total_spent"] = float(trend_entry["total_spent"]) + item.spent
        if item.status == "over":
            trend_entry["over_budget_count"] = int(trend_entry["over_budget_count"]) + 1

    popular_categories = [
        AdminPopularCategory.model_validate(item)
        for item in sorted(
            popular_map.values(),
            key=lambda value: (-int(value["budget_count"]), -float(value["total_spent"]), str(value["category_name"])),
        )
    ]
    budget_trends = [
        AdminBudgetTrend.model_validate(trend_map[key])
        for key in sorted(trend_map.keys())
    ]
    sorted_budgets = sorted(
        budget_rows,
        key=lambda item: _sort_value(
            {
                "month": item.month,
                "user_name": item.user_name,
                "user_email": item.user_email,
                "category_name": item.category_name,
                "amount": item.amount,
                "spent": item.spent,
                "remaining": item.remaining,
                "status": item.status,
                "created_at": item.created_at,
            }.get(sort_by, item.month)
        ),
        reverse=sort_order == "desc",
    )
    total = len(sorted_budgets)

    return AdminBudgetsResponse(
        total=total,
        limit=limit,
        offset=offset,
        sort_by=sort_by,
        sort_order=sort_order,
        budgets=_apply_pagination(sorted_budgets, limit, offset),
        overspending_analysis=AdminOverspendingAnalysis(
            over_budget_count=over_budget_count,
            near_limit_count=near_limit_count,
            total_budgeted=total_budgeted,
            total_spent=total_spent,
            total_overspent=total_overspent,
        ),
        popular_categories=popular_categories,
        budget_trends=budget_trends,
    )


@router.get("/insights", response_model=AdminInsightsResponse)
def list_admin_insights(
    user_id: int | None = Query(default=None),
    search: str | None = Query(default=None),
    severity: str | None = Query(default=None),
    date_from: date | None = Query(default=None),
    date_to: date | None = Query(default=None),
    limit: int = Query(default=10, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    sort_by: str = Query(default="created_at"),
    sort_order: Literal["asc", "desc"] = Query(default="desc"),
    db: Session = Depends(get_db),
):
    query = db.query(AIInsight, User.name, User.email).join(User, User.user_id == AIInsight.user_id)
    if user_id is not None:
        query = query.filter(AIInsight.user_id == user_id)
    pattern = _search_pattern(search)
    if pattern:
        query = query.filter(
            or_(
                func.lower(AIInsight.title).like(pattern),
                func.lower(AIInsight.message).like(pattern),
                func.lower(User.name).like(pattern),
                func.lower(User.email).like(pattern),
            )
        )
    if severity is not None:
        query = query.filter(AIInsight.severity == severity)
    if date_from is not None:
        query = query.filter(AIInsight.created_at >= datetime_for_date(date_from))
    if date_to is not None:
        query = query.filter(AIInsight.created_at < next_datetime_for_date(date_to))

    insights = []
    severity_counter: Counter[str] = Counter()
    trigger_counter: Counter[str] = Counter()
    for insight, user_name, user_email in query.order_by(AIInsight.created_at.desc()).all():
        insights.append(
            AdminInsightOut(
                insight_id=insight.insight_id,
                user_id=insight.user_id,
                user_name=user_name,
                user_email=user_email,
                title=insight.title,
                message=insight.message,
                severity=insight.severity,
                period_start=insight.period_start,
                period_end=insight.period_end,
                created_at=insight.created_at,
            )
        )
        severity_counter[insight.severity] += 1
        trigger_counter[insight.title] += 1

    severity_distribution = [
        AdminCountByLabel(label=label, count=count)
        for label, count in sorted(severity_counter.items(), key=lambda item: (-item[1], item[0]))
    ]
    trigger_frequency = [
        AdminCountByLabel(label=label, count=count)
        for label, count in sorted(trigger_counter.items(), key=lambda item: (-item[1], item[0]))
    ]
    sorted_insights = sorted(
        insights,
        key=lambda item: _sort_value(
            {
                "created_at": item.created_at,
                "title": item.title,
                "severity": item.severity,
                "user_name": item.user_name,
                "user_email": item.user_email,
                "period_start": item.period_start,
                "period_end": item.period_end,
            }.get(sort_by, item.created_at)
        ),
        reverse=sort_order == "desc",
    )
    return AdminInsightsResponse(
        total=len(sorted_insights),
        limit=limit,
        offset=offset,
        sort_by=sort_by,
        sort_order=sort_order,
        insights=_apply_pagination(sorted_insights, limit, offset),
        severity_distribution=severity_distribution,
        trigger_frequency=trigger_frequency,
    )


@router.get("/logs", response_model=AdminLogsResponse)
def list_admin_logs(
    search: str | None = Query(default=None),
    event_type: str | None = Query(default=None),
    level: str | None = Query(default=None),
    user_id: int | None = Query(default=None),
    admin_id: int | None = Query(default=None),
    date_from: date | None = Query(default=None),
    date_to: date | None = Query(default=None),
    limit: int = Query(default=10, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    sort_by: str = Query(default="created_at"),
    sort_order: Literal["asc", "desc"] = Query(default="desc"),
    db: Session = Depends(get_db),
):
    query = _logs_query(db)
    pattern = _search_pattern(search)
    if pattern:
        query = query.filter(
            or_(
                func.lower(SystemLog.event_type).like(pattern),
                func.lower(SystemLog.message).like(pattern),
                func.lower(func.coalesce(Admin.name, "")).like(pattern),
                func.lower(func.coalesce(User.name, "")).like(pattern),
                func.lower(func.coalesce(Admin.email, "")).like(pattern),
                func.lower(func.coalesce(User.email, "")).like(pattern),
            )
        )
    if event_type is not None:
        query = query.filter(SystemLog.event_type == event_type)
    if level is not None:
        query = query.filter(SystemLog.level == level)
    if user_id is not None:
        query = query.filter(SystemLog.user_id == user_id)
    if admin_id is not None:
        query = query.filter(SystemLog.admin_id == admin_id)
    if date_from is not None:
        query = query.filter(SystemLog.created_at >= datetime_for_date(date_from))
    if date_to is not None:
        query = query.filter(SystemLog.created_at < next_datetime_for_date(date_to))

    total = query.order_by(None).count()
    warning_count, error_count = query.order_by(None).with_entities(
        func.coalesce(func.sum(case((SystemLog.level == "warning", 1), else_=0)), 0),
        func.coalesce(func.sum(case((SystemLog.level.in_(["error", "critical"]), 1), else_=0)), 0),
    ).one()

    sort_columns = {
        "created_at": SystemLog.created_at,
        "event_type": SystemLog.event_type,
        "level": SystemLog.level,
        "message": SystemLog.message,
    }
    order_column = sort_columns.get(sort_by, SystemLog.created_at)
    logs = _serialize_logs(
        query.order_by(
            order_column.asc() if sort_order == "asc" else order_column.desc(),
            SystemLog.log_id.asc() if sort_order == "asc" else SystemLog.log_id.desc(),
        )
        .offset(offset)
        .limit(limit)
        .all()
    )
    return AdminLogsResponse(
        total=total,
        limit=limit,
        offset=offset,
        sort_by=sort_by,
        sort_order=sort_order,
        logs=logs,
        summary=AdminLogSummary(
            warning_count=int(warning_count or 0),
            error_count=int(error_count or 0),
        ),
    )
