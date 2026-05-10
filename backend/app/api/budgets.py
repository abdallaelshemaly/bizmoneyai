from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import extract
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.data_access import BudgetQueryFilters, list_budget_snapshots_for_user, query_budget_timeseries
from app.db.session import get_db
from app.models.budget import Budget
from app.models.category import Category
from app.models.user import User
from app.schemas.budget import BudgetCreate, BudgetOut, BudgetRecommendationOut, BudgetTimeSeriesPoint, BudgetUpdate
from app.services.admin_analytics import invalidate_admin_analytics_cache
from app.services.budget_metrics import normalize_month
from app.services import budget_recommender
from app.services.system_log import log_system_event

router = APIRouter(prefix="/budgets", tags=["budgets"])

DUPLICATE_BUDGET_MESSAGE = "Budget already exists for this category and month"


def _ensure_budget_category(db: Session, category_id: int, user_id: int) -> Category:
    category = (
        db.query(Category)
        .filter(Category.category_id == category_id, Category.user_id == user_id)
        .first()
    )
    if not category:
        raise HTTPException(status_code=400, detail="Invalid category for user")
    if category.type == "income":
        raise HTTPException(status_code=400, detail="Budgets can only be created for expense or both-type categories")
    return category


def _snapshot_for_budget(db: Session, user_id: int, budget: Budget) -> dict:
    snapshots = list_budget_snapshots_for_user(
        db,
        BudgetQueryFilters(user_id=user_id, month=budget.month),
    )
    return next(item for item in snapshots if item["budget_id"] == budget.budget_id)


def _duplicate_budget_query(
    db: Session,
    *,
    user_id: int,
    category_id: int,
    month: date,
    exclude_budget_id: int | None = None,
):
    normalized_month = normalize_month(month)
    query = db.query(Budget).filter(
        Budget.user_id == user_id,
        Budget.category_id == category_id,
        extract("year", Budget.month) == normalized_month.year,
        extract("month", Budget.month) == normalized_month.month,
    )
    if exclude_budget_id is not None:
        query = query.filter(Budget.budget_id != exclude_budget_id)
    return query


def _ensure_no_duplicate_budget(
    db: Session,
    *,
    user_id: int,
    category_id: int,
    month: date,
    exclude_budget_id: int | None = None,
) -> None:
    duplicate = _duplicate_budget_query(
        db,
        user_id=user_id,
        category_id=category_id,
        month=month,
        exclude_budget_id=exclude_budget_id,
    ).first()
    if duplicate:
        raise HTTPException(status_code=400, detail=DUPLICATE_BUDGET_MESSAGE)


def _is_duplicate_budget_integrity_error(exc: IntegrityError) -> bool:
    detail = str(exc.orig or exc).lower()
    return (
        "uq_budgets_user_category_month_year" in detail
        or "uq_budgets_user_category_month" in detail
        or (
            "unique constraint failed" in detail
            and "budgets.user_id" in detail
            and "budgets.category_id" in detail
            and "budgets.month" in detail
        )
        or (
            "duplicate key value violates unique constraint" in detail
            and ("uq_budgets_user_category_month_year" in detail or "uq_budgets_user_category_month" in detail)
        )
    )


def _commit_budget_changes(db: Session) -> None:
    try:
        db.commit()
        invalidate_admin_analytics_cache()
    except IntegrityError as exc:
        db.rollback()
        if _is_duplicate_budget_integrity_error(exc):
            raise HTTPException(status_code=400, detail=DUPLICATE_BUDGET_MESSAGE) from exc
        raise


@router.get("", response_model=list[BudgetOut])
def list_budgets(
    month: date | None = Query(default=None),
    month_from: date | None = Query(default=None),
    month_to: date | None = Query(default=None),
    category_id: int | None = Query(default=None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return list_budget_snapshots_for_user(
        db,
        BudgetQueryFilters(
            user_id=current_user.user_id,
            month=month,
            month_from=month_from,
            month_to=month_to,
            category_id=category_id,
        ),
    )


@router.get("/timeseries", response_model=list[BudgetTimeSeriesPoint])
def list_budget_timeseries(
    month: date | None = Query(default=None),
    month_from: date | None = Query(default=None),
    month_to: date | None = Query(default=None),
    category_id: int | None = Query(default=None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return query_budget_timeseries(
        db,
        BudgetQueryFilters(
            user_id=current_user.user_id,
            month=month,
            month_from=month_from,
            month_to=month_to,
            category_id=category_id,
        ),
    )


@router.get("/recommendations", response_model=list[BudgetRecommendationOut])
def list_budget_recommendations(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return budget_recommender.recommend_budgets_for_user(db, current_user)


@router.post("", response_model=BudgetOut, status_code=status.HTTP_201_CREATED)
def create_budget(
    payload: BudgetCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    category = _ensure_budget_category(db, payload.category_id, current_user.user_id)
    month = normalize_month(payload.month)
    data = payload.model_dump(exclude={"month"})
    _ensure_no_duplicate_budget(
        db,
        user_id=current_user.user_id,
        category_id=payload.category_id,
        month=month,
    )

    budget = Budget(user_id=current_user.user_id, **data, month=month)
    db.add(budget)
    db.flush()
    log_system_event(
        db,
        "create_budget",
        f"Created budget for category '{category.name}'",
        user_id=current_user.user_id,
        entity_id=budget.budget_id,
        metadata={
            "category_id": category.category_id,
            "category_name": category.name,
            "amount": budget.amount,
            "month": budget.month.isoformat(),
        },
    )
    _commit_budget_changes(db)
    db.refresh(budget)
    return _snapshot_for_budget(db, current_user.user_id, budget)


@router.put("/{budget_id}", response_model=BudgetOut)
def update_budget(
    budget_id: int,
    payload: BudgetUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    budget = (
        db.query(Budget)
        .filter(Budget.budget_id == budget_id, Budget.user_id == current_user.user_id)
        .first()
    )
    if not budget:
        raise HTTPException(status_code=404, detail="Budget not found")

    data = payload.model_dump(exclude_unset=True)
    category_id = data.get("category_id", budget.category_id)
    month = normalize_month(data.get("month", budget.month))
    category = _ensure_budget_category(db, category_id, current_user.user_id)
    _ensure_no_duplicate_budget(
        db,
        user_id=current_user.user_id,
        category_id=category_id,
        month=month,
        exclude_budget_id=budget_id,
    )

    for field, value in data.items():
        setattr(budget, field, normalize_month(value) if field == "month" else value)

    log_system_event(
        db,
        "update_budget",
        f"Updated budget for category '{category.name}'",
        user_id=current_user.user_id,
        entity_id=budget.budget_id,
        metadata={
            "category_id": category.category_id,
            "category_name": category.name,
            "amount": budget.amount,
            "month": budget.month.isoformat(),
        },
    )
    _commit_budget_changes(db)
    db.refresh(budget)
    return _snapshot_for_budget(db, current_user.user_id, budget)


@router.delete("/{budget_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_budget(
    budget_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    budget = (
        db.query(Budget)
        .filter(Budget.budget_id == budget_id, Budget.user_id == current_user.user_id)
        .first()
    )
    if not budget:
        raise HTTPException(status_code=404, detail="Budget not found")

    db.delete(budget)
    db.commit()
    invalidate_admin_analytics_cache()
    return None
