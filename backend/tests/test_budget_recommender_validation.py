from __future__ import annotations

import csv
from pathlib import Path

from app.ml.budgeting.train_budget_recommender import train
from app.ml.budgeting.validate_budget_recommender import (
    load_artifact,
    predict_runtime_recommendation,
    validate_budget_recommender,
)


FIELDNAMES = [
    "user_id",
    "business_profile",
    "company_size",
    "month",
    "category_name",
    "category_type",
    "clean_monthly_spend",
    "current_budget",
    "previous_month_spend",
    "prev_2_month_spend",
    "prev_3_month_spend",
    "avg_3_month_spend",
    "avg_6_month_spend",
    "growth_rate_3m",
    "budget_usage_ratio",
    "overspend_amount",
    "months_over_budget_3",
    "months_over_budget_6",
    "category_share_of_total",
    "total_clean_expense",
    "recommended_budget",
    "confidence_label",
]


def _row(
    index: int,
    *,
    clean_monthly_spend: float,
    current_budget: float,
    previous_month_spend: float,
    prev_2_month_spend: float,
    prev_3_month_spend: float,
    category_name: str,
    business_profile: str,
    company_size: str,
    category_type: str = "expense",
) -> dict[str, object]:
    return {
        "user_id": f"user_{index}",
        "business_profile": business_profile,
        "company_size": company_size,
        "month": f"2024-{(index % 12) + 1:02d}",
        "category_name": category_name,
        "category_type": category_type,
        "clean_monthly_spend": round(clean_monthly_spend, 2),
        "current_budget": round(current_budget, 2),
        "previous_month_spend": round(previous_month_spend, 2),
        "prev_2_month_spend": round(prev_2_month_spend, 2),
        "prev_3_month_spend": round(prev_3_month_spend, 2),
        "avg_3_month_spend": round((clean_monthly_spend + previous_month_spend + prev_2_month_spend) / 3.0, 2),
        "avg_6_month_spend": round(
            (clean_monthly_spend + previous_month_spend + prev_2_month_spend + prev_3_month_spend) / 4.0,
            2,
        ),
        "growth_rate_3m": round((clean_monthly_spend - prev_3_month_spend) / max(prev_3_month_spend, 1.0), 4),
        "budget_usage_ratio": round(clean_monthly_spend / max(current_budget, 1.0), 4),
        "overspend_amount": round(max(clean_monthly_spend - current_budget, 0.0), 2),
        "months_over_budget_3": 3 if clean_monthly_spend > current_budget else 0,
        "months_over_budget_6": 4 if clean_monthly_spend > current_budget else 0,
        "category_share_of_total": round(clean_monthly_spend / 8000.0, 4),
        "total_clean_expense": 8000.0,
        "recommended_budget": round(max(clean_monthly_spend * 1.15, current_budget * 1.05), 2),
        "confidence_label": "medium",
    }


def _sample_rows() -> list[dict[str, object]]:
    return [
        _row(1, clean_monthly_spend=2500.0, current_budget=3000.0, previous_month_spend=2480.0, prev_2_month_spend=2510.0, prev_3_month_spend=2490.0, category_name="Rent", business_profile="stable_company", company_size="small"),
        _row(2, clean_monthly_spend=2600.0, current_budget=3050.0, previous_month_spend=2580.0, prev_2_month_spend=2610.0, prev_3_month_spend=2570.0, category_name="Rent", business_profile="stable_company", company_size="small"),
        _row(3, clean_monthly_spend=1800.0, current_budget=1200.0, previous_month_spend=1450.0, prev_2_month_spend=1200.0, prev_3_month_spend=950.0, category_name="Marketing", business_profile="growing_business", company_size="medium"),
        _row(4, clean_monthly_spend=1950.0, current_budget=1300.0, previous_month_spend=1600.0, prev_2_month_spend=1300.0, prev_3_month_spend=1000.0, category_name="Marketing", business_profile="growing_business", company_size="medium"),
        _row(5, clean_monthly_spend=950.0, current_budget=700.0, previous_month_spend=910.0, prev_2_month_spend=880.0, prev_3_month_spend=860.0, category_name="Software", business_profile="lean_startup", company_size="micro"),
        _row(6, clean_monthly_spend=980.0, current_budget=720.0, previous_month_spend=930.0, prev_2_month_spend=900.0, prev_3_month_spend=870.0, category_name="Software", business_profile="lean_startup", company_size="micro"),
        _row(7, clean_monthly_spend=140.0, current_budget=220.0, previous_month_spend=135.0, prev_2_month_spend=145.0, prev_3_month_spend=130.0, category_name="Office Supplies", business_profile="stable_company", company_size="small"),
        _row(8, clean_monthly_spend=150.0, current_budget=210.0, previous_month_spend=142.0, prev_2_month_spend=146.0, prev_3_month_spend=138.0, category_name="Office Supplies", business_profile="stable_company", company_size="small"),
        _row(9, clean_monthly_spend=420.0, current_budget=450.0, previous_month_spend=430.0, prev_2_month_spend=410.0, prev_3_month_spend=425.0, category_name="Travel", business_profile="agency", company_size="small"),
        _row(10, clean_monthly_spend=430.0, current_budget=455.0, previous_month_spend=435.0, prev_2_month_spend=415.0, prev_3_month_spend=428.0, category_name="Travel", business_profile="agency", company_size="small"),
    ]


def _write_dataset(path: Path, rows: list[dict[str, object]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(rows)


def _trained_model(tmp_path: Path) -> tuple[Path, Path]:
    dataset_path = tmp_path / "budget_validation.csv"
    model_path = tmp_path / "budget_recommender.joblib"
    _write_dataset(dataset_path, _sample_rows())
    train(dataset_path=dataset_path, model_path=model_path, cluster_count=3)
    return dataset_path, model_path


def test_validation_script_runs(tmp_path: Path) -> None:
    dataset_path, model_path = _trained_model(tmp_path)
    result = validate_budget_recommender(model_path=model_path, dataset_path=dataset_path)
    assert result.dataset_rows > 0
    assert result.metrics["mae"] >= 0.0


def test_growing_category_gets_higher_recommendation(tmp_path: Path) -> None:
    _dataset_path, model_path = _trained_model(tmp_path)
    artifact = load_artifact(model_path)
    result = predict_runtime_recommendation(
        artifact,
        {
            "clean_monthly_spend": 1800.0,
            "current_budget": 1200.0,
            "previous_month_spend": 1450.0,
            "prev_2_month_spend": 1200.0,
            "prev_3_month_spend": 950.0,
            "avg_3_month_spend": 1483.33,
            "avg_6_month_spend": 1320.00,
            "growth_rate_3m": 0.8947,
            "budget_usage_ratio": 1.5000,
            "overspend_amount": 600.0,
            "months_over_budget_3": 3.0,
            "months_over_budget_6": 5.0,
            "category_share_of_total": 0.22,
            "total_clean_expense": 9000.0,
            "category_name": "Marketing",
            "business_profile": "growing_business",
            "company_size": "medium",
        },
        reason="test",
        scenario_name="growing",
    )
    assert result.recommended_budget > result.current_budget


def test_stable_category_does_not_jump_too_much(tmp_path: Path) -> None:
    _dataset_path, model_path = _trained_model(tmp_path)
    artifact = load_artifact(model_path)
    result = predict_runtime_recommendation(
        artifact,
        {
            "clean_monthly_spend": 2500.0,
            "current_budget": 3000.0,
            "previous_month_spend": 2485.0,
            "prev_2_month_spend": 2510.0,
            "prev_3_month_spend": 2495.0,
            "avg_3_month_spend": 2498.33,
            "avg_6_month_spend": 2502.50,
            "growth_rate_3m": 0.0020,
            "budget_usage_ratio": 0.8333,
            "overspend_amount": 0.0,
            "months_over_budget_3": 0.0,
            "months_over_budget_6": 0.0,
            "category_share_of_total": 0.21,
            "total_clean_expense": 12000.0,
            "category_name": "Rent",
            "business_profile": "stable_company",
            "company_size": "small",
        },
        reason="test",
        scenario_name="stable",
    )
    assert abs(result.recommended_budget - result.current_budget) <= 750.0


def test_recommendation_is_positive_and_capped_safely(tmp_path: Path) -> None:
    _dataset_path, model_path = _trained_model(tmp_path)
    artifact = load_artifact(model_path)
    result = predict_runtime_recommendation(
        artifact,
        {
            "clean_monthly_spend": 140.0,
            "current_budget": 220.0,
            "previous_month_spend": 135.0,
            "prev_2_month_spend": 145.0,
            "prev_3_month_spend": 130.0,
            "avg_3_month_spend": 140.00,
            "avg_6_month_spend": 142.00,
            "growth_rate_3m": 0.0769,
            "budget_usage_ratio": 0.6364,
            "overspend_amount": 0.0,
            "months_over_budget_3": 0.0,
            "months_over_budget_6": 0.0,
            "category_share_of_total": 0.02,
            "total_clean_expense": 4800.0,
            "category_name": "Office Supplies",
            "business_profile": "stable_company",
            "company_size": "small",
        },
        reason="test",
        scenario_name="small_stable",
    )
    assert result.recommended_budget > 0.0
    assert result.recommended_budget <= 400.0


def test_unusual_spike_does_not_inflate_recommendation(tmp_path: Path) -> None:
    _dataset_path, model_path = _trained_model(tmp_path)
    artifact = load_artifact(model_path)
    result = predict_runtime_recommendation(
        artifact,
        {
            "clean_monthly_spend": 420.0,
            "current_budget": 450.0,
            "previous_month_spend": 430.0,
            "prev_2_month_spend": 410.0,
            "prev_3_month_spend": 425.0,
            "avg_3_month_spend": 420.00,
            "avg_6_month_spend": 418.00,
            "growth_rate_3m": -0.0118,
            "budget_usage_ratio": 0.9333,
            "overspend_amount": 0.0,
            "months_over_budget_3": 0.0,
            "months_over_budget_6": 0.0,
            "category_share_of_total": 0.04,
            "total_clean_expense": 6000.0,
            "category_name": "Travel",
            "business_profile": "agency",
            "company_size": "small",
        },
        reason="test",
        scenario_name="spike_excluded",
    )
    assert result.recommended_budget <= 900.0
