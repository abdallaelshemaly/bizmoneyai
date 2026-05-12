from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel


class AIInsightOut(BaseModel):
    insight_id: int
    user_id: int
    rule_id: str | None = None
    title: str
    message: str
    severity: Literal["info", "warning", "critical"]
    period_start: date
    period_end: date
    created_at: datetime

    class Config:
        from_attributes = True


class AIInsightRankedOut(AIInsightOut):
    priority_score: float
    priority_level: Literal["low", "medium", "high", "critical"]
    priority_reason: str


class AIInsightGenerateRequest(BaseModel):
    period_start: date | None = None
    period_end: date | None = None


class AIInsightClearResponse(BaseModel):
    deleted_count: int
    message: str


class AIInsightTimeSeriesPoint(BaseModel):
    bucket: date
    insights_count: int
    info_count: int
    warning_count: int
    critical_count: int
