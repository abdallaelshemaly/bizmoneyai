# Model 4: Smart Budget Recommender Report

## 1. Executive Summary

BizMoneyAI Model 4 is the **Smart Budget Recommender**, a machine learning feature that suggests more realistic monthly budgets for the user's expense categories. Its role is to turn recent clean spending behavior into practical budget guidance inside the product.

The current implementation uses:

- `RandomForestRegressor` for budget recommendation prediction
- `KMeans` for lightweight behavior grouping
- generated BizMoneyAI-style data for training and validation
- real database data at runtime

Kaggle was **not** used for Model 4. The project currently does not have enough production user history to train a stable budgeting model directly from real app usage, so the model is trained on generated BizMoneyAI-style data and then applied to live user data at runtime.

At the current project phase, Model 4 is:

- trained
- validated
- integrated into the backend runtime
- exposed through an authenticated API
- displayed in the user frontend
- covered by runtime scenario tests
- optionally connected to `AIInsight` creation for meaningful recommendations

It is ready for the current project phase, while still carrying the normal limitations of synthetic training data and early-stage production history.

## 2. Introduction

BizMoneyAI already supports category prediction, unusual transaction detection, spending forecasting, budgets, and rule-based insights. Model 4 extends that stack by adding recommendation logic for **how much a user should budget next month for each expense category**.

This shifts the product from simple tracking toward more proactive financial planning.

## 3. Problem Statement

Users can create budgets manually, but those budget amounts are not always aligned with actual category behavior. A budget may be too low because spending has grown steadily, or too high because the category has stabilized at a lower level.

The product therefore needs a model that answers this question:

**What monthly budget amount is realistic for this expense category based on recent clean behavior?**

The answer must avoid distortion from unusual spikes, warning-level anomalies, and fraud-like transactions.

## 4. Model Goal and Vision

The goal of Model 4 is to recommend a realistic **monthly budget amount per expense category**.

Its vision inside BizMoneyAI is to:

- help users set better category budgets
- reduce reactive budgeting
- connect historical spending, anomaly filtering, and AI guidance into one budgeting workflow
- provide explainable suggestions rather than black-box outputs

## 5. Dataset

Training and validation dataset:

```text
backend/data/processed/bizmoneyai_budget_recommender.csv
```

Dataset facts:

- rows: `33600`
- task type: category-level budget recommendation regression
- target column: `recommended_budget`

Core columns include:

- `clean_monthly_spend`
- `current_budget`
- `previous_month_spend`
- `prev_2_month_spend`
- `prev_3_month_spend`
- `avg_3_month_spend`
- `avg_6_month_spend`
- `growth_rate_3m`
- `budget_usage_ratio`
- `overspend_amount`
- `months_over_budget_3`
- `months_over_budget_6`
- `category_share_of_total`
- `total_clean_expense`
- `category_name`
- `business_profile`
- `company_size`

## 6. Why Only Generated BizMoneyAI Data Is Used

Kaggle was not used for Model 4.

Generated BizMoneyAI-style data was used because:

- the project does not yet have enough production user data for stable model training
- the product needs feature contracts that match BizMoneyAI behavior, not a generic public dataset
- the generated dataset can reflect the app's own budgeting and spending concepts directly

This was the most practical approach for the current stage of the project. Real production data can improve the model later, especially once the application has enough diverse user history across months and categories.

## 7. Preprocessing

Model 4 preprocessing follows strict leakage and quality rules:

- use only `backend/data/processed/bizmoneyai_budget_recommender.csv`
- exclude `recommended_budget` from features
- exclude identifier and non-generalizable fields such as `user_id`
- exclude constant or non-useful fields such as `category_type` when they do not vary
- exclude future target style columns if present
- exclude raw unusual or fraud spike fields if present
- exclude income categories

At runtime, the service also excludes live transactions already flagged by Model 2 as unusual.

## 8. Feature Engineering

Model 4 uses category-level budget and clean-spending features rather than raw transaction sequences.

Important engineered inputs include:

- `clean_monthly_spend`
- `current_budget`
- `previous_month_spend`
- `prev_2_month_spend`
- `prev_3_month_spend`
- `avg_3_month_spend`
- `avg_6_month_spend`
- `growth_rate_3m`
- `budget_usage_ratio`
- `overspend_amount`
- `months_over_budget_3`
- `months_over_budget_6`
- `category_share_of_total`
- `total_clean_expense`

Categorical context includes:

- `category_name`
- `business_profile`
- `company_size`

At runtime, `business_profile` and `company_size` are currently conservative defaults because the live database does not yet store those fields directly.

## 9. Algorithm

Model 4 uses a two-part machine learning design:

- `RandomForestRegressor`
- `KMeans`

This combines supervised recommendation with unsupervised behavior grouping.

## 10. RandomForestRegressor Role

`RandomForestRegressor` is the main predictive model.

Its job is to estimate the recommended monthly category budget based on:

- recent clean spend
- recent spending trend
- budget pressure
- overspending frequency
- category-level context

It was chosen because:

- it handles mixed structured features well
- it works with modest synthetic datasets
- it is robust for tabular business data
- it is straightforward to integrate and validate

## 11. KMeans Clustering Role

`KMeans` is not used as the main recommender. It is used to group budget behavior patterns into cluster labels such as:

- stable behavior groups
- budget pressure groups
- stronger growth or overspending groups

This gives the frontend and insight layer a lightweight behavioral grouping signal without making clustering the main decision engine.

## 12. Training Process

Training script:

```text
backend/app/ml/budgeting/train_budget_recommender.py
```

Training process:

1. Load the generated Model 4 dataset.
2. Validate the required columns.
3. Filter to expense categories only.
4. Exclude leakage columns.
5. Train `RandomForestRegressor`.
6. Train `KMeans` on selected behavior features.
7. Save the artifact.

Artifact path:

```text
backend/app/ml/models/budget_recommender.joblib
```

The artifact includes:

- trained regressor
- trained cluster model
- preprocessors
- feature columns
- target column
- cluster labels and cluster summary
- metrics
- metadata including model family and algorithm description

## 13. Validation Metrics

Validation script:

```text
backend/app/ml/budgeting/validate_budget_recommender.py
```

Latest reported validation metrics on the generated dataset:

- MAE: `22.8021`
- RMSE: `55.7463`
- R2: `0.9977`
- MAPE: `0.0221`

These numbers show strong performance on generated BizMoneyAI-style data. They should be interpreted as a validation result for the current synthetic training setup, not as proof of production-perfect performance on future live user budgeting behavior.

## 14. Runtime Backend Integration

Runtime service:

```text
backend/app/services/budget_recommender.py
```

The service:

- loads `backend/app/ml/models/budget_recommender.joblib`
- confirms the artifact feature contract
- builds runtime features from real database records
- excludes unusual transactions linked to Model 2 warning or critical insights
- returns per-category recommendation objects
- falls back safely when the model is unavailable or history is insufficient

The service does not create or modify `Budget` rows when returning recommendations.

## 15. API Endpoint

Authenticated endpoint:

```text
GET /budgets/recommendations
```

The response includes:

- `category_id`
- `category_name`
- `current_budget`
- `recommended_budget`
- `confidence_level`
- `behavior_group`
- `cluster_label`
- `reason`
- `expected_change_amount`
- `expected_change_percent`
- `months_used`

The route is read-only and preserves existing budget CRUD behavior.

## 16. Frontend Integration

Primary page:

```text
frontend/user/src/app/budgets/page.tsx
```

Secondary page:

```text
frontend/user/src/app/dashboard/page.tsx
```

Frontend behavior:

- budgets page shows Model 4 recommendations near existing budgets
- dashboard shows a small "Recommended Budget Adjustments" card
- income categories are not shown
- endpoint failure does not crash the page
- calm fallback text appears when recommendations are unavailable

The current frontend pass is display-only. It does not implement an Apply button yet.

## 17. AIInsight Integration If Implemented

Model 4 now has optional AI insight creation for meaningful recommendations.

Rule id:

```text
ml_budget_recommendation
```

Insight creation rules:

- only when the recommendation is meaningful
- only for `medium` or `high` confidence
- no insight for tiny changes

The persisted insight includes structured metadata such as:

- `category_id`
- `category_name`
- `current_budget`
- `recommended_budget`
- `expected_change_amount`
- `expected_change_percent`
- `confidence_level`
- `behavior_group`
- `target_month`
- `scope_key`

## 18. Model 2 Unusual Transaction Exclusion

Model 4 excludes transactions linked to:

- `AIInsight.rule_id = "ml_unusual_transaction"`
- severity `warning` or `critical`

This prevents extreme or suspicious amounts from inflating live budgeting recommendations.

This design mirrors the clean-behavior principle already used in the forecasting workflow.

## 19. Test Scenarios

Model 4 is covered by multiple test layers, including:

- dataset audit checks
- training contract checks
- validation scenario checks
- backend runtime service tests
- authenticated API tests
- runtime scenario tests with DB-shaped data
- optional AI insight tests

Important runtime scenarios include:

- stable rent account
- growing marketing
- software repeatedly over budget
- unusual spike exclusion
- insufficient history fallback

These tests verify that recommendations stay realistic, safe, explainable, and non-destructive.

## 20. Advantages

Model 4 provides several advantages for the current BizMoneyAI phase:

- uses BizMoneyAI-style budgeting concepts directly
- excludes unusual transactions from runtime aggregation
- integrates with live user data
- remains explainable
- supports frontend display cleanly
- supports optional AI insight creation
- preserves existing budget CRUD behavior

## 21. Limitations

Current limitations include:

- training uses generated data rather than real production budgeting history
- runtime uses conservative defaults for `business_profile` and `company_size`
- the clustering layer is lightweight and descriptive, not deeply personalized
- recommendations are useful guidance, not guaranteed optimal budgets
- the model should not be described as production-perfect

## 22. Future Work

Likely future improvements include:

- retrain Model 4 on real production data once enough history exists
- add richer live user profile features if the product later stores them
- improve cluster interpretation and labeling
- compare alternative regressors once real data volume grows
- add user feedback loops for accepted versus ignored recommendations
- optionally add a safe Apply flow after month-target behavior is fully specified

## 23. Conclusion

Model 4 successfully adds intelligent budget recommendation to BizMoneyAI for the current phase of the project.

It is built on generated BizMoneyAI-style data because the app does not yet have enough real production history for robust direct training. Even so, the live runtime uses actual user transactions, budgets, categories, and insights, and it excludes unusual Model 2 transactions so recommendations stay grounded in normal behavior.

The current result is a practical, explainable, integrated budgeting feature that is ready for the current project phase and positioned to improve further once real production data becomes available.

## 24. Report Input for ChatGPT

Use the following framing when discussing Model 4:

- Model name: `Smart Budget Recommender`
- Purpose: recommend realistic monthly budgets for expense categories
- Training data: generated BizMoneyAI-style data only
- Kaggle usage: not used
- Runtime data: real BizMoneyAI database data
- Core algorithms: `RandomForestRegressor` plus `KMeans`
- Clean-spending rule: exclude Model 2 unusual transaction insights with `warning` or `critical` severity
- Backend endpoint: `GET /budgets/recommendations`
- Frontend surfaces: budgets page and dashboard card
- Optional insight rule: `ml_budget_recommendation`
- Current status: implemented, trained, validated, integrated, and tested for the current project phase
- Important limitation: real production data can improve the model later
