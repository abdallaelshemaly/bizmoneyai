from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.models.ai_insight import AIInsight

UNUSUAL_TRANSACTION_RULE_ID = "ml_unusual_transaction"
UNUSUAL_TRANSACTION_MESSAGES = {
    "warning": "Unusual transaction detected. This transaction appears higher risk than normal.",
    "critical": "Critical unusual transaction detected. Review this transaction immediately.",
}

_SEVERITY_RANK = {"warning": 1, "critical": 2}


def _optional_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _optional_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def transaction_fraud_statuses(
    db: Session,
    *,
    transaction_ids: set[int],
    user_id: int | None = None,
) -> dict[int, dict[str, object | None]]:
    if not transaction_ids:
        return {}

    query = db.query(AIInsight).filter(
        AIInsight.rule_id == UNUSUAL_TRANSACTION_RULE_ID,
        AIInsight.severity.in_(["warning", "critical"]),
    )
    if user_id is not None:
        query = query.filter(AIInsight.user_id == user_id)

    statuses: dict[int, dict[str, object | None]] = {}
    for insight in query.order_by(AIInsight.created_at.desc(), AIInsight.insight_id.desc()).all():
        metadata = insight.metadata_json or {}
        transaction_id = _optional_int(metadata.get("transaction_id"))
        if transaction_id is None or transaction_id not in transaction_ids:
            continue

        existing = statuses.get(transaction_id)
        existing_rank = _SEVERITY_RANK.get(str(existing.get("fraud_risk_level")) if existing else "", 0)
        current_rank = _SEVERITY_RANK.get(insight.severity, 0)
        if existing is not None and existing_rank >= current_rank:
            continue

        statuses[transaction_id] = {
            "fraud_insight_id": insight.insight_id,
            "fraud_risk_level": insight.severity,
            "fraud_probability": _optional_float(metadata.get("fraud_probability")),
        }

    return statuses
