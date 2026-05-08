from datetime import date as dt_date

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
