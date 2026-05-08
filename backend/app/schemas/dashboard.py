from typing import Literal

from pydantic import BaseModel


class MonthlyTrendPoint(BaseModel):
    month: str
    income: float
    expense: float


class CategoryBreakdownItem(BaseModel):
    category_name: str
    total: float


class DashboardSummary(BaseModel):
    total_income: float
    total_expense: float
    balance: float
    expense_ratio: float
    savings_rate: float
    monthly_average_income: float
    monthly_average_expense: float
    transaction_count: int
    budget_total: float
    budget_spent: float
    budget_remaining: float
    over_budget_count: int
    budget_month: str
    top_expense_category_name: str | None
    top_expense_category_total: float
    health_status: Literal["healthy", "watch", "at_risk"]
    focus_message: str
    monthly_trend: list[MonthlyTrendPoint]
    category_breakdown: list[CategoryBreakdownItem]
