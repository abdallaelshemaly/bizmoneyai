from datetime import date, datetime
from typing import Any
from typing import Literal

from pydantic import BaseModel, EmailStr


class AdminCountByLabel(BaseModel):
    label: str
    count: int


class AdminActivityTrend(BaseModel):
    date: date
    users: int = 0
    transactions: int = 0
    categories: int = 0
    budgets: int = 0
    insights: int = 0
    logs: int = 0
    total_events: int = 0


class AdminTransactionTrend(BaseModel):
    date: date
    transactions_count: int = 0
    total_amount: float = 0.0


class AdminSpendDistributionItem(BaseModel):
    category_name: str
    total_amount: float
    transactions_count: int


class AdminOverspendingCategory(BaseModel):
    category_name: str
    over_budget_count: int
    total_overspent: float


class AdminActiveUser(BaseModel):
    user_id: int
    name: str
    email: EmailStr
    transactions_count: int
    categories_count: int
    budgets_count: int
    insights_count: int
    activity_score: int
    last_activity: datetime | None


class AdminLogRow(BaseModel):
    log_id: int
    event_type: str
    level: str
    message: str
    created_at: datetime
    metadata: dict[str, Any] | None = None
    admin_id: int | None = None
    admin_name: str | None = None
    admin_email: EmailStr | None = None
    user_id: int | None = None
    user_name: str | None = None
    user_email: EmailStr | None = None


class AdminUnusualTransactionInsight(BaseModel):
    insight_id: int
    user_id: int
    user_name: str
    user_email: EmailStr
    title: str
    message: str
    severity: Literal["warning", "critical"]
    period_start: date
    period_end: date
    created_at: datetime
    transaction_id: int | None = None
    fraud_probability: float | None = None


class AdminPaginationMeta(BaseModel):
    total: int
    limit: int
    offset: int
    sort_by: str | None = None
    sort_order: Literal["asc", "desc"] = "desc"


class AdminDashboardOut(BaseModel):
    total_users: int
    total_transactions: int
    total_categories: int
    total_budgets: int
    total_ai_insights: int
    activity_trends: list[AdminActivityTrend]
    transaction_trends: list[AdminTransactionTrend]
    insight_severity_distribution: list[AdminCountByLabel]
    spend_distribution: list[AdminSpendDistributionItem]
    top_overspending_categories: list[AdminOverspendingCategory]
    most_active_users: list[AdminActiveUser]
    over_budget_categories: int
    total_overspending_amount: float
    total_unusual_transactions: int
    unusual_warning_count: int
    unusual_critical_count: int
    recent_unusual_transaction_insights: list[AdminUnusualTransactionInsight]
    recent_logs: list[AdminLogRow]


class AdminAnalyticsOverviewOut(BaseModel):
    total_users: int
    total_transactions: int
    total_categories: int
    total_budgets: int
    total_ai_insights: int
    activity_trends: list[AdminActivityTrend]
    recent_logs: list[AdminLogRow]


class AdminAnalyticsTransactionsOut(BaseModel):
    transaction_trends: list[AdminTransactionTrend]
    spend_distribution: list[AdminSpendDistributionItem]


class AdminAnalyticsUsersOut(BaseModel):
    most_active_users: list[AdminActiveUser]


class AdminAnalyticsInsightsOut(BaseModel):
    insight_severity_distribution: list[AdminCountByLabel]
    total_unusual_transactions: int
    unusual_warning_count: int
    unusual_critical_count: int
    recent_unusual_transaction_insights: list[AdminUnusualTransactionInsight]


class AdminAnalyticsBudgetsOut(BaseModel):
    top_overspending_categories: list[AdminOverspendingCategory]
    over_budget_categories: int
    total_overspending_amount: float


class AdminUserRow(BaseModel):
    user_id: int
    name: str
    email: EmailStr
    is_active: bool
    created_at: datetime
    transactions_count: int
    categories_count: int
    budgets_count: int
    insights_count: int
    last_activity: datetime | None


class AdminUserSummary(BaseModel):
    active_count: int
    inactive_count: int


class AdminUserFinancialSummary(BaseModel):
    total_income: float
    total_expense: float
    balance: float
    over_budget_count: int


class AdminUsersResponse(AdminPaginationMeta):
    users: list[AdminUserRow]
    summary: AdminUserSummary


class AdminUserStatusUpdate(BaseModel):
    is_active: bool


class AdminTransactionOut(BaseModel):
    transaction_id: int
    user_id: int
    user_name: str
    user_email: EmailStr
    category_id: int
    category_name: str
    amount: float
    type: Literal["income", "expense"]
    description: str | None
    date: date
    created_at: datetime
    fraud_risk_level: Literal["warning", "critical"] | None = None
    fraud_probability: float | None = None
    fraud_insight_id: int | None = None


class AdminTransactionSummary(BaseModel):
    total_amount: float
    income_count: int
    expense_count: int


class AdminTransactionsResponse(AdminPaginationMeta):
    transactions: list[AdminTransactionOut]
    summary: AdminTransactionSummary


class AdminCategoryOut(BaseModel):
    category_id: int
    user_id: int
    user_name: str
    user_email: EmailStr
    name: str
    type: Literal["income", "expense", "both"]
    transactions_count: int
    budgets_count: int
    created_at: datetime


class AdminCategorySummary(BaseModel):
    income_count: int
    expense_count: int
    both_count: int


class AdminCategoriesResponse(AdminPaginationMeta):
    categories: list[AdminCategoryOut]
    summary: AdminCategorySummary


class AdminDefaultCategoryOut(BaseModel):
    user_id: int
    category_id: int
    name: str
    type: Literal["income", "expense", "both"]


class AdminDefaultCategoriesResult(BaseModel):
    target_user_count: int
    created_count: int
    created: list[AdminDefaultCategoryOut]


class AdminBudgetRow(BaseModel):
    budget_id: int
    user_id: int
    user_name: str
    user_email: EmailStr
    category_id: int
    category_name: str
    amount: float
    spent: float
    remaining: float
    status: Literal["on_track", "near_limit", "over"]
    month: date
    note: str | None
    created_at: datetime


class AdminOverspendingAnalysis(BaseModel):
    over_budget_count: int
    near_limit_count: int
    total_budgeted: float
    total_spent: float
    total_overspent: float


class AdminPopularCategory(BaseModel):
    category_name: str
    budget_count: int
    total_budgeted: float
    total_spent: float


class AdminBudgetTrend(BaseModel):
    month: str
    budgets_count: int
    total_budgeted: float
    total_spent: float
    over_budget_count: int


class AdminBudgetsResponse(AdminPaginationMeta):
    budgets: list[AdminBudgetRow]
    overspending_analysis: AdminOverspendingAnalysis
    popular_categories: list[AdminPopularCategory]
    budget_trends: list[AdminBudgetTrend]


class AdminInsightOut(BaseModel):
    insight_id: int
    user_id: int
    user_name: str
    user_email: EmailStr
    title: str
    message: str
    severity: Literal["info", "warning", "critical"]
    period_start: date
    period_end: date
    created_at: datetime


class AdminUserOverview(BaseModel):
    user: AdminUserRow
    financial_summary: AdminUserFinancialSummary
    recent_logs: list[AdminLogRow]
    recent_insights: list[AdminInsightOut]


class AdminInsightsResponse(AdminPaginationMeta):
    insights: list[AdminInsightOut]
    severity_distribution: list[AdminCountByLabel]
    trigger_frequency: list[AdminCountByLabel]


class AdminLogSummary(BaseModel):
    warning_count: int
    error_count: int


class AdminLogsResponse(AdminPaginationMeta):
    logs: list[AdminLogRow]
    summary: AdminLogSummary
