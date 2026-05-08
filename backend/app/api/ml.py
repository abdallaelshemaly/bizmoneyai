import logging
from dataclasses import dataclass

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.category import Category
from app.models.user import User
from app.schemas.ml import (
    DetectUnusualTransactionRequest,
    DetectUnusualTransactionResponse,
    PredictCategoryRequest,
    PredictCategoryResponse,
)
from app.services.category_classifier import classifier
from app.services.category_classifier import normalize_category_name
from app.services.embeddings import cosine_similarity, embed_texts
from app.services import fraud_detector
from app.services.system_log import log_system_event

router = APIRouter(prefix="/ml", tags=["ml"])
logger = logging.getLogger(__name__)

MAX_LOG_TEXT_LENGTH = 160


@dataclass(frozen=True)
class PredictionResult:
    response: PredictCategoryResponse
    method: str
    predicted_label: str | None
    matched_category: str | None
    confidence: float


def _truncate_for_log(value: str) -> str:
    normalized = " ".join(value.split())
    if len(normalized) <= MAX_LOG_TEXT_LENGTH:
        return normalized
    return f"{normalized[: MAX_LOG_TEXT_LENGTH - 3]}..."


def _log_prediction_event(
    db: Session,
    *,
    user_id: int,
    text: str,
    result: PredictionResult,
) -> None:
    try:
        log_system_event(
            db,
            "ml_category_prediction",
            f"ML category prediction used {result.method}",
            user_id=user_id,
            metadata={
                "input_text": _truncate_for_log(text),
                "predicted_label": result.predicted_label,
                "matched_category": result.matched_category,
                "confidence": result.confidence,
                "method": result.method,
            },
        )
        db.commit()
    except Exception:
        db.rollback()
        logger.exception("Failed to log ML category prediction event")


def _embedding_prediction(text: str, categories: list[Category]) -> PredictionResult:
    texts = [text] + [f"{category.name} {category.type}" for category in categories]
    vectors = embed_texts(texts)
    base = vectors[0]

    best_score = -1.0
    best_idx = 0
    for idx, vec in enumerate(vectors[1:], start=0):
        score = cosine_similarity(base, vec)
        if score > best_score:
            best_score = score
            best_idx = idx

    best = categories[best_idx]
    confidence = max(0.0, min(1.0, (best_score + 1) / 2))
    rounded_confidence = round(confidence, 4)
    response = PredictCategoryResponse(
        suggested_category_id=best.category_id,
        suggested_category_name=best.name,
        confidence=rounded_confidence,
    )
    return PredictionResult(
        response=response,
        method="embedding_fallback",
        predicted_label=best.name,
        matched_category=best.name,
        confidence=rounded_confidence,
    )


@router.post("/predict-category", response_model=PredictCategoryResponse)
def predict_category(
    payload: PredictCategoryRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    categories = db.query(Category).filter(Category.user_id == current_user.user_id).all()
    if not categories:
        response = PredictCategoryResponse(
            suggested_category_id=None,
            suggested_category_name=None,
            confidence=0.0,
        )
        result = PredictionResult(
            response=response,
            method="no_categories",
            predicted_label=None,
            matched_category=None,
            confidence=0.0,
        )
        _log_prediction_event(db, user_id=current_user.user_id, text=payload.text, result=result)
        return response

    category_by_name = {normalize_category_name(category.name): category for category in categories}
    classifier_prediction = classifier.predict(payload.text, [category.name for category in categories])
    if classifier_prediction is not None:
        matched_category = category_by_name.get(normalize_category_name(classifier_prediction.matched_category))
        if matched_category is not None:
            response = PredictCategoryResponse(
                suggested_category_id=matched_category.category_id,
                suggested_category_name=matched_category.name,
                confidence=classifier_prediction.confidence,
            )
            result = PredictionResult(
                response=response,
                method="classifier",
                predicted_label=classifier_prediction.predicted_label,
                matched_category=matched_category.name,
                confidence=classifier_prediction.confidence,
            )
            _log_prediction_event(db, user_id=current_user.user_id, text=payload.text, result=result)
            return response

    result = _embedding_prediction(payload.text, categories)
    _log_prediction_event(db, user_id=current_user.user_id, text=payload.text, result=result)
    return result.response


@router.post(
    "/detect-unusual-transaction",
    response_model=DetectUnusualTransactionResponse,
)
def detect_unusual_transaction(
    payload: DetectUnusualTransactionRequest,
    current_user: User = Depends(get_current_user),
):
    _ = current_user
    prediction_payload = {
        "amount": payload.amount,
        "type": payload.transaction_type,
        "category_name": payload.category_name,
        "description": payload.description,
        "date": payload.date.isoformat() if payload.date is not None else None,
        "budget_amount": payload.budget_amount,
        "budget_spent_before": payload.budget_spent_before,
        "budget_usage_ratio": payload.budget_usage_ratio,
        "user_avg_amount": payload.user_avg_amount,
        "category_avg_amount": payload.category_avg_amount,
        "recent_transaction_count": payload.recent_transaction_count,
    }
    try:
        result = fraud_detector.predict(prediction_payload)
    except Exception:
        logger.exception("Fraud detection service failed")
        result = {
            "is_unusual": False,
            "fraud_probability": 0.0,
            "risk_level": "normal",
            "model_name": None,
        }
    return DetectUnusualTransactionResponse(**result)
