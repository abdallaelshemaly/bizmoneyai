from datetime import date as dt_date
from typing import Literal

from pydantic import BaseModel


class PredictCategoryRequest(BaseModel):
    text: str


class PredictCategoryResponse(BaseModel):
    suggested_category_id: int | None
    suggested_category_name: str | None
    confidence: float


class DetectUnusualTransactionRequest(BaseModel):
    amount: float
    transaction_type: str | None = None
    category_name: str | None = None
    description: str | None = None
    date: dt_date | None = None
    budget_amount: float | None = None
    budget_spent_before: float | None = None
    budget_usage_ratio: float | None = None
    user_avg_amount: float | None = None
    category_avg_amount: float | None = None
    recent_transaction_count: int | None = None
    step: int | None = None
    oldbalanceOrg: float | None = None
    newbalanceOrig: float | None = None
    oldbalanceDest: float | None = None
    newbalanceDest: float | None = None


class DetectUnusualTransactionResponse(BaseModel):
    is_unusual: bool
    fraud_probability: float
    risk_level: str
    model_name: str | None = None


class SpendingForecastResponse(BaseModel):
    predicted_next_month_expense: float | None
    confidence_level: Literal["low", "medium", "high", "unavailable"]
    model_name: str
    months_used: int
    current_month_expense: float
    previous_month_expense: float
    rolling_3_month_expense_avg: float
    budget_total: float
    forecast_vs_budget: float | None
    top_reduction_categories: list[str]
    recommendation: str
