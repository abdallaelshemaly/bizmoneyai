from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class BudgetBase(BaseModel):
    category_id: int
    amount: float = Field(gt=0)
    month: date
    note: str | None = Field(default=None, max_length=255)

    @model_validator(mode="after")
    def normalize(self):
        self.month = self.month.replace(day=1)
        return self


class BudgetCreate(BudgetBase):
    pass


class BudgetUpdate(BaseModel):
    category_id: int | None = None
    amount: float | None = Field(default=None, gt=0)
    month: date | None = None
    note: str | None = Field(default=None, max_length=255)

    @model_validator(mode="after")
    def normalize(self):
        if self.month is not None:
            self.month = self.month.replace(day=1)
        return self


class BudgetOut(BaseModel):
    budget_id: int
    user_id: int
    category_id: int
    category_name: str
    amount: float
    spent: float
    remaining: float
    status: Literal["on_track", "near_limit", "over"]
    month: date
    note: str | None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class BudgetTimeSeriesPoint(BaseModel):
    bucket: date
    budgets_count: int
    total_budgeted: float
    total_spent: float
    over_budget_count: int


class BudgetRecommendationOut(BaseModel):
    category_id: int
    category_name: str
    current_budget: float
    recommended_budget: float
    confidence_level: Literal["low", "medium", "high", "unavailable"]
    behavior_group: str
    cluster_label: str
    reason: str
    expected_change_amount: float
    expected_change_percent: float
    months_used: int
