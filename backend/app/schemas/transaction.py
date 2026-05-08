from datetime import date as dt_date, datetime
from typing import Literal

from pydantic import BaseModel, Field


class TransactionCreate(BaseModel):
    category_id: int
    amount: float = Field(gt=0)
    type: Literal["income", "expense"]
    description: str | None = None
    date: dt_date


class TransactionUpdate(BaseModel):
    category_id: int | None = None
    amount: float | None = Field(default=None, gt=0)
    type: Literal["income", "expense"] | None = None
    description: str | None = None
    date: dt_date | None = None


class TransactionOut(BaseModel):
    transaction_id: int
    user_id: int
    category_id: int
    amount: float
    type: Literal["income", "expense"]
    description: str | None
    date: dt_date
    created_at: datetime
    fraud_risk_level: Literal["warning", "critical"] | None = None
    fraud_probability: float | None = None
    fraud_insight_id: int | None = None

    class Config:
        from_attributes = True


class TransactionTimeSeriesPoint(BaseModel):
    bucket: dt_date
    transactions_count: int
    income_total: float
    expense_total: float
    net_total: float


class TransactionImportRejectedRow(BaseModel):
    row_number: int
    reason: str


class TransactionImportResult(BaseModel):
    imported_count: int
    skipped_count: int
    rejected_rows: list[TransactionImportRejectedRow]
    transactions: list[TransactionOut]
