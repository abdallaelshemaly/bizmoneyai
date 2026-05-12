from __future__ import annotations

from calendar import monthrange
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.budget import Budget
from app.models.category import Category
from app.models.transaction import Transaction
from app.services.budget_metrics import normalize_month


@dataclass(frozen=True)
class DateRange:
    start: date
    end: date

    @property
    def day_count(self) -> int:
        return (self.end - self.start).days + 1

    @property
    def is_full_month_span(self) -> bool:
        return self.start == normalize_month(self.start) and self.end == date(
            self.end.year,
            self.end.month,
            monthrange(self.end.year, self.end.month)[1],
        )


@dataclass
class CategoryTotals:
    category_id: int
    category_name: str
    income_total: float = 0.0
    expense_total: float = 0.0


@dataclass
class PeriodMetrics:
    total_income: float = 0.0
    total_expense: float = 0.0
    largest_income_amount: float = 0.0
    largest_expense_amount: float = 0.0
    category_totals: dict[int, CategoryTotals] = field(default_factory=dict)

    @property
    def balance(self) -> float:
        return float(self.total_income - self.total_expense)

    @property
    def expense_ratio(self) -> float | None:
        if self.total_income <= 0:
            return None
        return float(self.total_expense / self.total_income)


@dataclass(frozen=True)
class BudgetSnapshot:
    budget_id: int
    category_id: int
    category_name: str
    month: date
    amount: float
    spent: float

    @property
    def usage_ratio(self) -> float | None:
        if self.amount <= 0:
            return None
        return float(self.spent / self.amount)

    @property
    def overspend_amount(self) -> float:
        return float(max(self.spent - self.amount, 0.0))


@dataclass(frozen=True)
class MonthlyExpenseSnapshot:
    category_id: int
    category_name: str
    month: date
    spent: float


@dataclass(frozen=True)
class MonthlyComparison:
    current_period: DateRange
    previous_period: DateRange
    current: PeriodMetrics
    previous: PeriodMetrics


@dataclass(frozen=True)
class InsightCalculationContext:
    user_id: int
    current_period: DateRange
    previous_period: DateRange
    current: PeriodMetrics
    previous: PeriodMetrics
    monthly_comparison: MonthlyComparison | None
    current_monthly_expenses: tuple[MonthlyExpenseSnapshot, ...]
    current_budgets: tuple[BudgetSnapshot, ...]
    consecutive_overspend_counts: dict[tuple[int, date], int]

    @property
    def budgeted_category_ids(self) -> set[int]:
        return {budget.category_id for budget in self.current_budgets}

    @property
    def budgeted_category_months(self) -> set[tuple[int, date]]:
        return {(budget.category_id, budget.month) for budget in self.current_budgets}


def build_insight_context(
    db: Session,
    *,
    user_id: int,
    period_start: date,
    period_end: date,
) -> InsightCalculationContext:
    current_period = DateRange(start=period_start, end=period_end)
    previous_period = _previous_period(current_period)

    current_metrics = _load_period_metrics(db, user_id=user_id, period=current_period)
    previous_metrics = _load_period_metrics(db, user_id=user_id, period=previous_period)
    monthly_comparison = _build_monthly_comparison(
        db,
        user_id=user_id,
        current_period=current_period,
    )

    months_in_period = _month_starts_between(period_start, period_end)
    current_monthly_expenses = tuple(
        _load_monthly_expense_snapshots(
            db,
            user_id=user_id,
            period=current_period,
        )
    )
    current_budgets = tuple(_load_budget_snapshots(db, user_id=user_id, months=months_in_period))
    consecutive_counts = _load_consecutive_overspend_counts(
        db,
        user_id=user_id,
        current_budgets=current_budgets,
    )

    return InsightCalculationContext(
        user_id=user_id,
        current_period=current_period,
        previous_period=previous_period,
        current=current_metrics,
        previous=previous_metrics,
        monthly_comparison=monthly_comparison,
        current_monthly_expenses=current_monthly_expenses,
        current_budgets=current_budgets,
        consecutive_overspend_counts=consecutive_counts,
    )


def _previous_period(current_period: DateRange) -> DateRange:
    previous_end = current_period.start - timedelta(days=1)
    previous_start = previous_end - timedelta(days=current_period.day_count - 1)
    return DateRange(start=previous_start, end=previous_end)


def _build_monthly_comparison(
    db: Session,
    *,
    user_id: int,
    current_period: DateRange,
) -> MonthlyComparison | None:
    if not current_period.is_full_month_span:
        return None

    previous_period = _previous_full_month_period(current_period)
    return MonthlyComparison(
        current_period=current_period,
        previous_period=previous_period,
        current=_load_period_metrics(db, user_id=user_id, period=current_period),
        previous=_load_period_metrics(db, user_id=user_id, period=previous_period),
    )
def _previous_full_month_period(current_period: DateRange) -> DateRange:
    months_in_period = _month_starts_between(current_period.start, current_period.end)
    previous_end = current_period.start - timedelta(days=1)
    previous_start = normalize_month(previous_end)
    for _ in range(len(months_in_period) - 1):
        previous_start = _previous_month_start(previous_start)
    return DateRange(start=previous_start, end=previous_end)


def _previous_month_start(value: date) -> date:
    normalized = normalize_month(value)
    if normalized.month == 1:
        return normalized.replace(year=normalized.year - 1, month=12)
    return normalized.replace(month=normalized.month - 1)


def _load_period_metrics(
    db: Session,
    *,
    user_id: int,
    period: DateRange,
) -> PeriodMetrics:
    rows = (
        db.query(
            Transaction.amount,
            Transaction.type,
            Transaction.category_id,
            Category.name,
        )
        .join(Category, Category.category_id == Transaction.category_id)
        .filter(
            Transaction.user_id == user_id,
            Category.user_id == user_id,
            Transaction.date >= period.start,
            Transaction.date <= period.end,
        )
        .all()
    )

    metrics = PeriodMetrics()
    category_totals: dict[int, CategoryTotals] = {}
    for amount, transaction_type, category_id, category_name in rows:
        normalized_type = str(transaction_type).lower()
        amount_value = float(amount or 0.0)
        category_entry = category_totals.setdefault(
            int(category_id),
            CategoryTotals(
                category_id=int(category_id),
                category_name=str(category_name),
            ),
        )

        if normalized_type == "income":
            metrics.total_income += amount_value
            category_entry.income_total += amount_value
            metrics.largest_income_amount = max(metrics.largest_income_amount, amount_value)
        else:
            metrics.total_expense += amount_value
            category_entry.expense_total += amount_value
            metrics.largest_expense_amount = max(metrics.largest_expense_amount, amount_value)

    metrics.category_totals = category_totals
    return metrics


def _load_budget_snapshots(
    db: Session,
    *,
    user_id: int,
    months: tuple[date, ...],
) -> list[BudgetSnapshot]:
    if not months:
        return []

    month_start = min(months)
    month_end = _next_month_start(max(months))

    rows = (
        db.query(Budget, Category.name)
        .join(Category, Category.category_id == Budget.category_id)
        .filter(
            Budget.user_id == user_id,
            Category.user_id == user_id,
            Budget.month >= month_start,
            Budget.month < month_end,
        )
        .all()
    )
    latest_rows = _latest_budget_rows(rows)
    spend_map = _expense_spend_by_category_month(
        db,
        user_id=user_id,
        category_ids=tuple(sorted({budget.category_id for budget, _ in latest_rows})),
        range_start=month_start,
        range_end=_month_end(max(months)),
    )

    snapshots: list[BudgetSnapshot] = []
    for budget, category_name in sorted(
        latest_rows,
        key=lambda item: (normalize_month(item[0].month), str(item[1]).lower(), item[0].budget_id),
    ):
        budget_month = normalize_month(budget.month)
        snapshots.append(
            BudgetSnapshot(
                budget_id=int(budget.budget_id),
                category_id=int(budget.category_id),
                category_name=str(category_name),
                month=budget_month,
                amount=float(budget.amount),
                spent=float(spend_map.get((int(budget.category_id), budget_month), 0.0)),
            )
        )
    return snapshots


def _load_monthly_expense_snapshots(
    db: Session,
    *,
    user_id: int,
    period: DateRange,
) -> list[MonthlyExpenseSnapshot]:
    rows = (
        db.query(
            Transaction.category_id,
            Category.name,
            Transaction.date,
            Transaction.amount,
        )
        .join(Category, Category.category_id == Transaction.category_id)
        .filter(
            Transaction.user_id == user_id,
            Category.user_id == user_id,
            func.lower(Transaction.type) == "expense",
            Transaction.date >= period.start,
            Transaction.date <= period.end,
        )
        .all()
    )

    grouped: dict[tuple[int, date], MonthlyExpenseSnapshot] = {}
    for category_id, category_name, tx_date, amount in rows:
        month = normalize_month(tx_date)
        key = (int(category_id), month)
        existing = grouped.get(key)
        if existing is None:
            grouped[key] = MonthlyExpenseSnapshot(
                category_id=int(category_id),
                category_name=str(category_name),
                month=month,
                spent=float(amount or 0.0),
            )
            continue

        grouped[key] = MonthlyExpenseSnapshot(
            category_id=existing.category_id,
            category_name=existing.category_name,
            month=existing.month,
            spent=float(existing.spent + float(amount or 0.0)),
        )

    return sorted(
        grouped.values(),
        key=lambda item: (item.month, item.category_name.lower(), item.category_id),
    )


def _load_consecutive_overspend_counts(
    db: Session,
    *,
    user_id: int,
    current_budgets: tuple[BudgetSnapshot, ...],
) -> dict[tuple[int, date], int]:
    if not current_budgets:
        return {}

    category_ids = tuple(sorted({budget.category_id for budget in current_budgets}))
    max_month = max(budget.month for budget in current_budgets)

    history_rows = (
        db.query(Budget, Category.name)
        .join(Category, Category.category_id == Budget.category_id)
        .filter(
            Budget.user_id == user_id,
            Category.user_id == user_id,
            Budget.category_id.in_(category_ids),
            Budget.month < _next_month_start(max_month),
        )
        .all()
    )
    latest_rows = _latest_budget_rows(history_rows)
    if not latest_rows:
        return {}

    min_month = min(normalize_month(budget.month) for budget, _ in latest_rows)
    spend_map = _expense_spend_by_category_month(
        db,
        user_id=user_id,
        category_ids=category_ids,
        range_start=min_month,
        range_end=_month_end(max_month),
    )

    history_by_category: dict[int, list[BudgetSnapshot]] = defaultdict(list)
    for budget, category_name in latest_rows:
        budget_month = normalize_month(budget.month)
        history_by_category[int(budget.category_id)].append(
            BudgetSnapshot(
                budget_id=int(budget.budget_id),
                category_id=int(budget.category_id),
                category_name=str(category_name),
                month=budget_month,
                amount=float(budget.amount),
                spent=float(spend_map.get((int(budget.category_id), budget_month), 0.0)),
            )
        )

    consecutive_counts: dict[tuple[int, date], int] = {}
    for category_id, snapshots in history_by_category.items():
        snapshots.sort(key=lambda item: item.month)
        current_streak = 0
        previous_month: date | None = None
        for snapshot in snapshots:
            if previous_month is not None and snapshot.month != _next_month_start(previous_month):
                current_streak = 0
            if snapshot.spent > snapshot.amount:
                current_streak = current_streak + 1 if previous_month is None or snapshot.month == _next_month_start(previous_month) else 1
            else:
                current_streak = 0
            consecutive_counts[(category_id, snapshot.month)] = current_streak
            previous_month = snapshot.month

    return consecutive_counts


def _latest_budget_rows(rows: list[tuple[Budget, str]]) -> list[tuple[Budget, str]]:
    selected: dict[tuple[int, date], tuple[Budget, str]] = {}
    for budget, category_name in rows:
        key = (int(budget.category_id), normalize_month(budget.month))
        existing = selected.get(key)
        if existing is None:
            selected[key] = (budget, category_name)
            continue

        existing_budget = existing[0]
        existing_marker = (
            existing_budget.created_at or datetime.min,
            int(existing_budget.budget_id),
        )
        candidate_marker = (
            budget.created_at or datetime.min,
            int(budget.budget_id),
        )
        if candidate_marker >= existing_marker:
            selected[key] = (budget, category_name)
    return list(selected.values())


def _expense_spend_by_category_month(
    db: Session,
    *,
    user_id: int,
    category_ids: tuple[int, ...],
    range_start: date,
    range_end: date,
) -> dict[tuple[int, date], float]:
    if not category_ids:
        return {}

    rows = (
        db.query(
            Transaction.category_id,
            Transaction.date,
            Transaction.amount,
        )
        .filter(
            Transaction.user_id == user_id,
            Transaction.category_id.in_(category_ids),
            func.lower(Transaction.type) == "expense",
            Transaction.date >= range_start,
            Transaction.date <= range_end,
        )
        .all()
    )

    spend_map: dict[tuple[int, date], float] = defaultdict(float)
    for category_id, tx_date, amount in rows:
        spend_map[(int(category_id), normalize_month(tx_date))] += float(amount or 0.0)
    return dict(spend_map)


def _month_starts_between(start: date, end: date) -> tuple[date, ...]:
    month = normalize_month(start)
    last_month = normalize_month(end)
    months: list[date] = []
    while month <= last_month:
        months.append(month)
        month = _next_month_start(month)
    return tuple(months)


def _next_month_start(value: date) -> date:
    normalized = normalize_month(value)
    if normalized.month == 12:
        return normalized.replace(year=normalized.year + 1, month=1)
    return normalized.replace(month=normalized.month + 1)


def _month_end(value: date) -> date:
    normalized = normalize_month(value)
    return date(
        normalized.year,
        normalized.month,
        monthrange(normalized.year, normalized.month)[1],
    )
