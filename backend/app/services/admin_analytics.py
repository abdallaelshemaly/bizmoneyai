from copy import deepcopy
from datetime import date, datetime, timedelta
from threading import Lock
from time import monotonic
from typing import Callable, TypeVar

from sqlalchemy import and_, extract, func, select
from sqlalchemy.orm import Session

from app.core.time import utcnow
from app.models.admin import Admin
from app.models.ai_insight import AIInsight
from app.models.budget import Budget
from app.models.category import Category
from app.models.system_log import SystemLog
from app.models.transaction import Transaction
from app.models.user import User
from app.schemas.admin_panel import (
    AdminActiveUser,
    AdminActivityTrend,
    AdminAnalyticsBudgetsOut,
    AdminForecastRiskInsight,
    AdminAnalyticsInsightsOut,
    AdminAnalyticsOverviewOut,
    AdminAnalyticsTransactionsOut,
    AdminAnalyticsUsersOut,
    AdminCountByLabel,
    AdminDashboardOut,
    AdminLogRow,
    AdminOverspendingCategory,
    AdminSpendDistributionItem,
    AdminTransactionTrend,
    AdminUnusualTransactionInsight,
)
from app.services.budget_metrics import budget_status

CACHE_TTL_SECONDS = 30
UNUSUAL_TRANSACTION_RULE_ID = "ml_unusual_transaction"
FORECAST_RISK_RULE_ID = "ml_spending_forecast_risk"

_T = TypeVar("_T")
_analytics_cache: dict[tuple[str, int | None, int | None], tuple[float, object]] = {}
_analytics_cache_lock = Lock()


def invalidate_admin_analytics_cache() -> None:
    with _analytics_cache_lock:
        _analytics_cache.clear()


def _cache_key(namespace: str, *, user_id: int | None, days: int | None) -> tuple[str, int | None, int | None]:
    return (namespace, user_id, days)


def _with_ttl_cache(
    namespace: str,
    *,
    user_id: int | None,
    days: int | None,
    builder: Callable[[], _T],
) -> _T:
    key = _cache_key(namespace, user_id=user_id, days=days)
    now = monotonic()
    with _analytics_cache_lock:
        cached = _analytics_cache.get(key)
        if cached and cached[0] > now:
            return deepcopy(cached[1])  # type: ignore[return-value]

    value = builder()
    with _analytics_cache_lock:
        _analytics_cache[key] = (now + CACHE_TTL_SECONDS, value)
    return deepcopy(value)


def _datetime_for_date(value: date) -> datetime:
    return utcnow().replace(year=value.year, month=value.month, day=value.day, hour=0, minute=0, second=0, microsecond=0)


def _coerce_group_date(value: object) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value))


def _created_count_map(db: Session, model, since_date: date, user_id: int | None = None) -> dict[date, int]:
    bucket = func.date(model.created_at)
    query = (
        db.query(bucket.label("created_day"), func.count().label("count"))
        .filter(model.created_at >= _datetime_for_date(since_date))
    )
    if user_id is not None:
        query = query.filter(model.user_id == user_id)
    return {
        _coerce_group_date(created_day): int(count or 0)
        for created_day, count in query.group_by(bucket).all()
    }


def _serialize_logs(rows) -> list[AdminLogRow]:
    return [
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
        for log, admin_name, admin_email, user_name, user_email in rows
    ]


def _logs_query(db: Session):
    return (
        db.query(SystemLog, Admin.name, Admin.email, User.name, User.email)
        .outerjoin(Admin, Admin.admin_id == SystemLog.admin_id)
        .outerjoin(User, User.user_id == SystemLog.user_id)
    )


def _optional_int(value: object) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _optional_float(value: object) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _serialize_unusual_transaction_insights(rows) -> list[AdminUnusualTransactionInsight]:
    serialized: list[AdminUnusualTransactionInsight] = []
    for insight, user_name, user_email in rows:
        metadata = insight.metadata_json or {}
        serialized.append(
            AdminUnusualTransactionInsight(
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
                transaction_id=_optional_int(metadata.get("transaction_id")),
                fraud_probability=_optional_float(metadata.get("fraud_probability")),
            )
        )
    return serialized


def _serialize_forecast_risk_insights(rows) -> list[AdminForecastRiskInsight]:
    serialized: list[AdminForecastRiskInsight] = []
    for insight, user_name, user_email in rows:
        metadata = insight.metadata_json or {}
        categories = metadata.get("top_reduction_categories") or []
        serialized.append(
            AdminForecastRiskInsight(
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
                predicted_next_month_expense=_optional_float(metadata.get("predicted_next_month_expense")),
                budget_total=_optional_float(metadata.get("budget_total")),
                forecast_vs_budget=_optional_float(metadata.get("forecast_vs_budget")),
                confidence_level=str(metadata.get("confidence_level")) if metadata.get("confidence_level") is not None else None,
                top_reduction_categories=[str(category) for category in categories if str(category).strip()],
            )
        )
    return serialized


def _unusual_transaction_insights_query(db: Session, user_id: int | None = None):
    query = (
        db.query(AIInsight, User.name, User.email)
        .join(User, User.user_id == AIInsight.user_id)
        .filter(
            AIInsight.rule_id == UNUSUAL_TRANSACTION_RULE_ID,
            AIInsight.severity.in_(["warning", "critical"]),
        )
    )
    if user_id is not None:
        query = query.filter(AIInsight.user_id == user_id)
    return query


def _forecast_risk_insights_query(db: Session, user_id: int | None = None):
    query = (
        db.query(AIInsight, User.name, User.email)
        .join(User, User.user_id == AIInsight.user_id)
        .filter(
            AIInsight.rule_id == FORECAST_RISK_RULE_ID,
            AIInsight.severity.in_(["warning", "critical"]),
        )
    )
    if user_id is not None:
        query = query.filter(AIInsight.user_id == user_id)
    return query


def _count_records(db: Session, model, id_column, user_id: int | None = None) -> int:
    query = db.query(func.count(id_column))
    if user_id is not None:
        query = query.filter(model.user_id == user_id)
    return int(query.scalar() or 0)


def _user_metric_subquery(model, id_column, prefix: str, user_id: int | None = None):
    statement = select(
        model.user_id.label("user_id"),
        func.count(id_column).label(f"{prefix}_count"),
        func.max(model.created_at).label(f"{prefix}_last"),
    )
    if user_id is not None:
        statement = statement.where(model.user_id == user_id)
    return statement.group_by(model.user_id).subquery()


def get_admin_analytics_overview(
    db: Session,
    *,
    user_id: int | None = None,
    days: int = 30,
) -> AdminAnalyticsOverviewOut:
    def builder() -> AdminAnalyticsOverviewOut:
        total_users = _count_records(db, User, User.user_id, user_id=user_id)
        total_transactions = _count_records(db, Transaction, Transaction.transaction_id, user_id=user_id)
        total_categories = _count_records(db, Category, Category.category_id, user_id=user_id)
        total_budgets = _count_records(db, Budget, Budget.budget_id, user_id=user_id)
        total_ai_insights = _count_records(db, AIInsight, AIInsight.insight_id, user_id=user_id)

        since_date = (utcnow() - timedelta(days=days - 1)).date()
        users_map = _created_count_map(db, User, since_date, user_id=user_id)
        transactions_map = _created_count_map(db, Transaction, since_date, user_id=user_id)
        categories_map = _created_count_map(db, Category, since_date, user_id=user_id)
        budgets_map = _created_count_map(db, Budget, since_date, user_id=user_id)
        insights_map = _created_count_map(db, AIInsight, since_date, user_id=user_id)
        logs_map = _created_count_map(db, SystemLog, since_date, user_id=user_id)

        activity_trends = []
        for offset in range(days):
            point = since_date + timedelta(days=offset)
            users_count = users_map.get(point, 0)
            transactions_count = transactions_map.get(point, 0)
            categories_count = categories_map.get(point, 0)
            budgets_count = budgets_map.get(point, 0)
            insights_count = insights_map.get(point, 0)
            logs_count = logs_map.get(point, 0)
            activity_trends.append(
                AdminActivityTrend(
                    date=point,
                    users=users_count,
                    transactions=transactions_count,
                    categories=categories_count,
                    budgets=budgets_count,
                    insights=insights_count,
                    logs=logs_count,
                    total_events=users_count + transactions_count + categories_count + budgets_count + insights_count + logs_count,
                )
            )

        recent_logs_query = _logs_query(db)
        if user_id is not None:
            recent_logs_query = recent_logs_query.filter(SystemLog.user_id == user_id)
        recent_logs = _serialize_logs(
            recent_logs_query
            .order_by(SystemLog.created_at.desc(), SystemLog.log_id.desc())
            .limit(12)
            .all()
        )

        return AdminAnalyticsOverviewOut(
            total_users=total_users,
            total_transactions=total_transactions,
            total_categories=total_categories,
            total_budgets=total_budgets,
            total_ai_insights=total_ai_insights,
            activity_trends=activity_trends,
            recent_logs=recent_logs,
        )

    return _with_ttl_cache("overview", user_id=user_id, days=days, builder=builder)


def get_admin_analytics_transactions(
    db: Session,
    *,
    user_id: int | None = None,
    days: int = 30,
) -> AdminAnalyticsTransactionsOut:
    def builder() -> AdminAnalyticsTransactionsOut:
        since_date = (utcnow() - timedelta(days=days - 1)).date()

        tx_trend_query = (
            db.query(
                Transaction.date,
                func.count(Transaction.transaction_id),
                func.coalesce(func.sum(Transaction.amount), 0.0),
            )
            .filter(Transaction.date >= since_date)
        )
        if user_id is not None:
            tx_trend_query = tx_trend_query.filter(Transaction.user_id == user_id)
        tx_trend_rows = tx_trend_query.group_by(Transaction.date).all()
        tx_trend_map = {
            tx_date: {
                "transactions_count": int(count or 0),
                "total_amount": float(total_amount or 0.0),
            }
            for tx_date, count, total_amount in tx_trend_rows
        }
        transaction_trends = [
            AdminTransactionTrend(
                date=point,
                transactions_count=tx_trend_map.get(point, {}).get("transactions_count", 0),
                total_amount=tx_trend_map.get(point, {}).get("total_amount", 0.0),
            )
            for point in [since_date + timedelta(days=offset) for offset in range(days)]
        ]

        spend_distribution_query = (
            db.query(
                Category.name,
                func.coalesce(func.sum(Transaction.amount), 0.0),
                func.count(Transaction.transaction_id),
            )
            .join(Category, Category.category_id == Transaction.category_id)
            .filter(Transaction.type == "expense", Transaction.date >= since_date)
        )
        if user_id is not None:
            spend_distribution_query = spend_distribution_query.filter(
                Transaction.user_id == user_id,
                Category.user_id == user_id,
            )
        spend_distribution = [
            AdminSpendDistributionItem(
                category_name=category_name,
                total_amount=float(total_amount or 0.0),
                transactions_count=int(count or 0),
            )
            for category_name, total_amount, count in (
                spend_distribution_query
                .group_by(Category.category_id, Category.name)
                .order_by(func.coalesce(func.sum(Transaction.amount), 0.0).desc(), Category.name.asc())
                .limit(6)
                .all()
            )
        ]

        return AdminAnalyticsTransactionsOut(
            transaction_trends=transaction_trends,
            spend_distribution=spend_distribution,
        )

    return _with_ttl_cache("transactions", user_id=user_id, days=days, builder=builder)


def get_admin_analytics_users(
    db: Session,
    *,
    user_id: int | None = None,
) -> AdminAnalyticsUsersOut:
    def builder() -> AdminAnalyticsUsersOut:
        tx_subquery = _user_metric_subquery(Transaction, Transaction.transaction_id, "transactions", user_id=user_id)
        category_subquery = _user_metric_subquery(Category, Category.category_id, "categories", user_id=user_id)
        budget_subquery = _user_metric_subquery(Budget, Budget.budget_id, "budgets", user_id=user_id)
        insight_subquery = _user_metric_subquery(AIInsight, AIInsight.insight_id, "insights", user_id=user_id)

        query = (
            db.query(
                User.user_id,
                User.name,
                User.email,
                User.created_at,
                func.coalesce(tx_subquery.c.transactions_count, 0).label("transactions_count"),
                tx_subquery.c.transactions_last,
                func.coalesce(category_subquery.c.categories_count, 0).label("categories_count"),
                category_subquery.c.categories_last,
                func.coalesce(budget_subquery.c.budgets_count, 0).label("budgets_count"),
                budget_subquery.c.budgets_last,
                func.coalesce(insight_subquery.c.insights_count, 0).label("insights_count"),
                insight_subquery.c.insights_last,
            )
            .outerjoin(tx_subquery, tx_subquery.c.user_id == User.user_id)
            .outerjoin(category_subquery, category_subquery.c.user_id == User.user_id)
            .outerjoin(budget_subquery, budget_subquery.c.user_id == User.user_id)
            .outerjoin(insight_subquery, insight_subquery.c.user_id == User.user_id)
        )
        if user_id is not None:
            query = query.filter(User.user_id == user_id)

        most_active_users: list[AdminActiveUser] = []
        for row in query.all():
            activity_score = int(row.transactions_count) + int(row.categories_count) + int(row.budgets_count) + int(row.insights_count)
            last_activity = max(
                (
                    value
                    for value in [
                        row.created_at,
                        row.transactions_last,
                        row.categories_last,
                        row.budgets_last,
                        row.insights_last,
                    ]
                    if value is not None
                ),
                default=None,
            )
            most_active_users.append(
                AdminActiveUser(
                    user_id=row.user_id,
                    name=row.name,
                    email=row.email,
                    transactions_count=int(row.transactions_count or 0),
                    categories_count=int(row.categories_count or 0),
                    budgets_count=int(row.budgets_count or 0),
                    insights_count=int(row.insights_count or 0),
                    activity_score=activity_score,
                    last_activity=last_activity,
                )
            )

        oldest = _datetime_for_date(date(2000, 1, 1))
        most_active_users.sort(
            key=lambda item: (
                -item.activity_score,
                -item.transactions_count,
                -(item.last_activity or oldest).timestamp(),
                item.name.lower(),
            )
        )

        return AdminAnalyticsUsersOut(most_active_users=most_active_users[:5])

    return _with_ttl_cache("users", user_id=user_id, days=None, builder=builder)


def get_admin_analytics_insights(
    db: Session,
    *,
    user_id: int | None = None,
) -> AdminAnalyticsInsightsOut:
    def builder() -> AdminAnalyticsInsightsOut:
        severity_query = db.query(AIInsight.severity, func.count(AIInsight.insight_id))
        if user_id is not None:
            severity_query = severity_query.filter(AIInsight.user_id == user_id)

        unusual_summary_query = (
            db.query(AIInsight.severity, func.count(AIInsight.insight_id))
            .filter(
                AIInsight.rule_id == UNUSUAL_TRANSACTION_RULE_ID,
                AIInsight.severity.in_(["warning", "critical"]),
            )
        )
        if user_id is not None:
            unusual_summary_query = unusual_summary_query.filter(AIInsight.user_id == user_id)

        unusual_counts = {
            severity: int(count or 0)
            for severity, count in unusual_summary_query.group_by(AIInsight.severity).all()
        }
        recent_unusual_transaction_insights = _serialize_unusual_transaction_insights(
            _unusual_transaction_insights_query(db, user_id=user_id)
            .order_by(AIInsight.created_at.desc(), AIInsight.insight_id.desc())
            .limit(5)
            .all()
        )

        forecast_summary_query = (
            db.query(AIInsight.severity, func.count(AIInsight.insight_id))
            .filter(
                AIInsight.rule_id == FORECAST_RISK_RULE_ID,
                AIInsight.severity.in_(["warning", "critical"]),
            )
        )
        if user_id is not None:
            forecast_summary_query = forecast_summary_query.filter(AIInsight.user_id == user_id)

        forecast_counts = {
            severity: int(count or 0)
            for severity, count in forecast_summary_query.group_by(AIInsight.severity).all()
        }
        users_with_forecast_risk_query = db.query(func.count(func.distinct(AIInsight.user_id))).filter(
            AIInsight.rule_id == FORECAST_RISK_RULE_ID,
            AIInsight.severity.in_(["warning", "critical"]),
        )
        if user_id is not None:
            users_with_forecast_risk_query = users_with_forecast_risk_query.filter(AIInsight.user_id == user_id)
        users_with_forecast_risk = int(users_with_forecast_risk_query.scalar() or 0)
        recent_forecast_risk_insights = _serialize_forecast_risk_insights(
            _forecast_risk_insights_query(db, user_id=user_id)
            .order_by(AIInsight.created_at.desc(), AIInsight.insight_id.desc())
            .limit(5)
            .all()
        )

        return AdminAnalyticsInsightsOut(
            insight_severity_distribution=[
                AdminCountByLabel(label=label, count=int(count or 0))
                for label, count in (
                    severity_query
                    .group_by(AIInsight.severity)
                    .order_by(func.count(AIInsight.insight_id).desc(), AIInsight.severity.asc())
                    .all()
                )
            ],
            total_unusual_transactions=sum(unusual_counts.values()),
            unusual_warning_count=unusual_counts.get("warning", 0),
            unusual_critical_count=unusual_counts.get("critical", 0),
            recent_unusual_transaction_insights=recent_unusual_transaction_insights,
            forecast_risk_insights_count=sum(forecast_counts.values()),
            forecast_risk_warning_count=forecast_counts.get("warning", 0),
            forecast_risk_critical_count=forecast_counts.get("critical", 0),
            users_with_forecast_risk=users_with_forecast_risk,
            recent_forecast_risk_insights=recent_forecast_risk_insights,
        )

    return _with_ttl_cache("insights", user_id=user_id, days=None, builder=builder)


def get_admin_analytics_budgets(
    db: Session,
    *,
    user_id: int | None = None,
) -> AdminAnalyticsBudgetsOut:
    def builder() -> AdminAnalyticsBudgetsOut:
        spend_subquery = (
            db.query(
                Transaction.user_id.label("user_id"),
                Transaction.category_id.label("category_id"),
                extract("year", Transaction.date).label("tx_year"),
                extract("month", Transaction.date).label("tx_month"),
                func.coalesce(func.sum(Transaction.amount), 0.0).label("spent"),
            )
            .filter(Transaction.type == "expense")
        )
        if user_id is not None:
            spend_subquery = spend_subquery.filter(Transaction.user_id == user_id)
        spend_subquery = (
            spend_subquery
            .group_by(
                Transaction.user_id,
                Transaction.category_id,
                extract("year", Transaction.date),
                extract("month", Transaction.date),
            )
            .subquery()
        )

        budget_rows = (
            db.query(
                Category.name,
                Budget.amount,
                func.coalesce(spend_subquery.c.spent, 0.0).label("spent"),
            )
            .join(Category, Category.category_id == Budget.category_id)
            .outerjoin(
                spend_subquery,
                and_(
                    spend_subquery.c.user_id == Budget.user_id,
                    spend_subquery.c.category_id == Budget.category_id,
                    spend_subquery.c.tx_year == extract("year", Budget.month),
                    spend_subquery.c.tx_month == extract("month", Budget.month),
                ),
            )
            .filter(Category.user_id == Budget.user_id)
        )
        if user_id is not None:
            budget_rows = budget_rows.filter(Budget.user_id == user_id, Category.user_id == user_id)

        over_budget_categories = 0
        total_overspending_amount = 0.0
        overspending_map: dict[str, dict[str, float | int]] = {}
        for category_name, amount, spent in budget_rows.all():
            budget_amount = float(amount or 0.0)
            total_spent = float(spent or 0.0)
            if budget_status(total_spent, budget_amount) != "over":
                continue

            over_budget_categories += 1
            overspent = max(total_spent - budget_amount, 0.0)
            total_overspending_amount += overspent
            entry = overspending_map.setdefault(
                category_name,
                {"category_name": category_name, "over_budget_count": 0, "total_overspent": 0.0},
            )
            entry["over_budget_count"] = int(entry["over_budget_count"]) + 1
            entry["total_overspent"] = float(entry["total_overspent"]) + overspent

        top_overspending_categories = [
            AdminOverspendingCategory.model_validate(item)
            for item in sorted(
                overspending_map.values(),
                key=lambda value: (-float(value["total_overspent"]), -int(value["over_budget_count"]), str(value["category_name"])),
            )[:5]
        ]

        return AdminAnalyticsBudgetsOut(
            top_overspending_categories=top_overspending_categories,
            over_budget_categories=over_budget_categories,
            total_overspending_amount=float(total_overspending_amount),
        )

    return _with_ttl_cache("budgets", user_id=user_id, days=None, builder=builder)


def get_admin_dashboard_data(
    db: Session,
    *,
    user_id: int | None = None,
    days: int = 30,
) -> AdminDashboardOut:
    overview = get_admin_analytics_overview(db, user_id=user_id, days=days)
    transactions = get_admin_analytics_transactions(db, user_id=user_id, days=days)
    users = get_admin_analytics_users(db, user_id=user_id)
    insights = get_admin_analytics_insights(db, user_id=user_id)
    budgets = get_admin_analytics_budgets(db, user_id=user_id)
    return AdminDashboardOut(
        **overview.model_dump(),
        **transactions.model_dump(),
        **users.model_dump(),
        **insights.model_dump(),
        **budgets.model_dump(),
    )
