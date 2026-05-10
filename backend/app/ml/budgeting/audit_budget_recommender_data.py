from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd


DEFAULT_DATASET_PATH = (
    Path(__file__).resolve().parents[3]
    / "data"
    / "processed"
    / "bizmoneyai_budget_recommender.csv"
)

TARGET_COLUMN = "recommended_budget"
EXPLICIT_EXCLUDED_COLUMNS = {
    TARGET_COLUMN,
    "user_id",
    "confidence_label",
}
LEAKAGE_NAME_PARTS = (
    "future",
    "target",
    "label",
    "fraud",
    "unusual",
    "spike",
    "anomaly",
    "risk",
    "raw",
    "next_",
)
INCOME_NAME_PARTS = (
    "income",
    "revenue",
    "sales",
)


def _money_summary(df: pd.DataFrame, column: str) -> str:
    if column not in df.columns:
        return "n/a"

    summary = df[column].describe()
    return "\n".join(
        [
            f"- count: {int(summary['count'])}",
            f"- mean: {summary['mean']:.2f}",
            f"- std: {summary['std']:.2f}",
            f"- min: {summary['min']:.2f}",
            f"- 25%: {summary['25%']:.2f}",
            f"- 50%: {summary['50%']:.2f}",
            f"- 75%: {summary['75%']:.2f}",
            f"- max: {summary['max']:.2f}",
        ]
    )


def _print_distribution(df: pd.DataFrame, column: str, title: str) -> None:
    if column not in df.columns:
        print(f"{title}: n/a")
        return

    print(f"{title}:")
    counts = df[column].fillna("missing").value_counts(dropna=False)
    for value, count in counts.items():
        print(f"- {value}: {count}")


def _identify_columns(df: pd.DataFrame) -> dict[str, list[str] | str]:
    columns = list(df.columns)
    normalized = {column: column.lower() for column in columns}

    category_columns = [
        column
        for column in columns
        if "category" in normalized[column]
    ]
    budget_columns = [
        column
        for column in columns
        if "budget" in normalized[column]
    ]
    spending_columns = [
        column
        for column in columns
        if "spend" in normalized[column] or "expense" in normalized[column]
    ]
    clean_spending_columns = [
        column
        for column in spending_columns
        if "clean" in normalized[column]
    ]

    leakage_columns = sorted(
        {
            column
            for column in columns
            if column in EXPLICIT_EXCLUDED_COLUMNS
            or any(part in normalized[column] for part in LEAKAGE_NAME_PARTS)
        }
    )

    constant_columns = [
        column
        for column in columns
        if df[column].nunique(dropna=False) <= 1
    ]
    excluded_columns = sorted(set(leakage_columns + constant_columns))
    feature_columns = [
        column
        for column in columns
        if column not in excluded_columns
    ]

    return {
        "target_column": TARGET_COLUMN if TARGET_COLUMN in columns else "",
        "feature_columns": feature_columns,
        "category_columns": category_columns,
        "budget_columns": budget_columns,
        "spending_columns": spending_columns,
        "clean_spending_columns": clean_spending_columns,
        "excluded_columns": excluded_columns,
        "constant_columns": constant_columns,
        "leakage_columns": leakage_columns,
    }


def audit_dataset(dataset_path: Path) -> None:
    if not dataset_path.exists():
        raise FileNotFoundError(f"Budget recommender dataset not found at {dataset_path}")

    df = pd.read_csv(dataset_path)
    identified = _identify_columns(df)
    category_name_has_income = False
    if "category_name" in df.columns:
        category_name_has_income = df["category_name"].astype(str).str.lower().str.contains(
            "|".join(INCOME_NAME_PARTS),
            regex=True,
        ).any()

    print(f"Dataset path: {dataset_path}")
    print(f"Dataset shape: {df.shape}")

    print("All columns:")
    for column in df.columns:
        print(f"- {column}")

    print("Missing values:")
    missing_values = df.isna().sum()
    for column in df.columns:
        print(f"- {column}: {int(missing_values[column])}")

    print(f"Target column: {identified['target_column'] or 'not found'}")
    print("Feature columns:")
    for column in identified["feature_columns"]:
        print(f"- {column}")

    print("Category columns:")
    for column in identified["category_columns"]:
        print(f"- {column}")

    print("Budget/spending columns:")
    for column in [*identified["budget_columns"], *identified["spending_columns"]]:
        print(f"- {column}")

    print("Clean spending columns:")
    for column in identified["clean_spending_columns"]:
        print(f"- {column}")

    print("Target column summary:")
    print(_money_summary(df, TARGET_COLUMN))

    _print_distribution(df, "category_name", "Category distribution")
    _print_distribution(df, "business_profile", "Business profile distribution")
    _print_distribution(df, "company_size", "Company size distribution")

    print("Current budget summary:")
    print(_money_summary(df, "current_budget"))

    print("Recommended budget summary:")
    print(_money_summary(df, TARGET_COLUMN))

    print("Clean monthly spend summary:")
    print(_money_summary(df, "clean_monthly_spend"))

    print("Suspicious leakage columns:")
    for column in identified["leakage_columns"]:
        print(f"- {column}")
    if not identified["leakage_columns"]:
        print("- none detected")

    print("Constant columns that should be excluded:")
    for column in identified["constant_columns"]:
        print(f"- {column}")
    if not identified["constant_columns"]:
        print("- none detected")

    print("Columns excluded from training:")
    for column in identified["excluded_columns"]:
        print(f"- {column}")

    print(
        "Income categories present:",
        "yes" if category_name_has_income else "no",
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Audit the generated BizMoneyAI Model 4 budget recommender dataset."
    )
    parser.add_argument(
        "--dataset-path",
        type=Path,
        default=DEFAULT_DATASET_PATH,
        help="Path to the processed Model 4 CSV file.",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    audit_dataset(args.dataset_path)
