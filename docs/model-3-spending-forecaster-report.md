# Model 3: Spending Forecaster Report

## Executive Summary

BizMoneyAI Model 3 is the **Spending Forecaster**, a machine learning component designed to predict a user's **expected next-month normal spending**. Its purpose is to help users plan ahead, monitor likely budget pressure before it happens, and support more proactive financial decision-making inside the BizMoneyAI product.

The current implementation uses `RandomForestRegressor` and a feature-based monthly forecasting approach built on clean spending, income context, budget context, and recent spending history. The model is trained and validated on generated BizMoneyAI-style monthly financial data because the application is not yet launched with enough long-horizon real user history to support reliable production training. At runtime, however, the forecast is computed from real database transactions.

An important design rule defines the final behavior of Model 3: transactions already flagged by Model 2 as unusual are excluded from forecast aggregation. This ensures that abnormal spikes, suspicious transactions, or fraud-like behavior do not distort the estimate of a user's normal future spending.

The final implementation includes:

- training script
- validation script
- saved model artifact
- backend runtime service
- authenticated API endpoint
- user dashboard forecast card
- optional forecast-risk AI insight creation
- lightweight admin visibility based on persisted AI insights

Latest reported evaluation metrics on the generated dataset are:

- R2: `0.9105`
- MAE: `1460.1375`
- RMSE: `2304.8601`
- MAPE: `0.115`

The model is therefore positioned as a practical forecasting feature for BizMoneyAI v1: useful, explainable, and integrated into the product, while still acknowledging the limitations of synthetic training data and early-stage deployment.

## Introduction

BizMoneyAI is designed to help users manage business finances more intelligently through transaction analysis, budget monitoring, AI insight generation, and predictive assistance. Early machine learning work in the product focused on classification and anomaly detection, but predictive budgeting support requires a forward-looking model.

Model 3 was introduced to fill that role. Instead of only reporting what a user already spent, the system should also estimate what they are likely to spend next month under normal business behavior. This allows BizMoneyAI to move from descriptive analytics toward practical forecasting and budget planning support.

## Problem Statement

Users often discover overspending only after the month is already underway or after budgets have already been exceeded. Historical summaries and budget dashboards are useful, but they do not answer a critical planning question:

**What is the user's likely normal spending next month if recent patterns continue?**

This problem becomes more challenging when transaction history includes unusual or suspicious amounts. If those spikes are treated as ordinary monthly behavior, the resulting forecast can become distorted and much less useful. Therefore, the forecasting system must estimate expected normal spending while protecting itself from anomaly leakage.

## Model Goal and Vision

The goal of Model 3 is to predict **expected next-month normal spending** for the logged-in user.

Its vision inside BizMoneyAI is to:

- help users plan ahead rather than react late
- identify upcoming budget risk before overspending happens
- connect budgeting, spending history, and AI recommendations into one forecasting workflow

The model is not intended to guarantee future spending exactly. Instead, it provides a practical estimate of normal expected spending based on recent clean behavior and financial context.

## Why Spending Forecasting is Useful in BizMoneyAI

Spending forecasting is useful in BizMoneyAI for several reasons:

- it adds forward-looking value beyond historical reports
- it helps users understand whether current spending habits are likely to pressure next month's budget
- it creates an earlier intervention point for budget control
- it enables recommendation-style guidance rather than passive reporting alone

In product terms, this means BizMoneyAI can warn users before budget problems appear instead of only describing them afterward.

## Data Strategy

Model 3 uses a two-part data strategy:

- **generated monthly BizMoneyAI-style data** for training and validation
- **real database transaction history** for runtime forecasting

This approach was chosen because the app is not launched with enough real long-horizon user history to train a stable production-grade forecasting model yet. Generated data makes it possible to define the feature contract, validate clean-spending forecasting behavior, and ship an integrated first version of the model. Real database history is then used at runtime so the live forecast still reflects the actual user's behavior in the app.

This strategy keeps implementation practical while preserving a path for future retraining on real production data.

## Generated Dataset

Training and validation dataset:

```text
backend/data/processed/bizmoneyai_spending_forecast.csv
```

Dataset facts:

- rows: `14000`
- task type: monthly spending regression
- target column: `next_month_total_expense`

The dataset is structured as monthly financial snapshots. Each row contains a set of clean-spending, budget, and behavioral features for the current month, along with the next month's clean total expense target.

The dataset intentionally follows BizMoneyAI-style business finance behavior rather than generic benchmark finance data. This allows the training contract to stay aligned with what the product actually wants to predict.

## Runtime Database Data

At runtime, Model 3 uses real database records rather than generated rows.

The service aggregates user history from existing tables, including:

- `transactions`
- `categories`
- `budgets`
- `ai_insights`

From these records, the backend builds monthly clean-spending snapshots and then generates the feature row required by the trained artifact. This means the live forecast is grounded in the user's actual behavior inside BizMoneyAI rather than static generated examples.

## Why Model 2 Warning/Critical Transactions Are Excluded

One of the most important final design decisions in Model 3 is the exclusion of unusual transactions already identified by Model 2.

Exclusion rule:

- exclude transactions linked to `AIInsight.rule_id = "ml_unusual_transaction"`
- only when severity is `warning` or `critical`

This rule exists because unusual or fraud-like transactions should not distort normal spending forecasts.

If those transactions were included in monthly aggregation, they could:

- inflate current-month expense totals
- distort historical lag features
- distort rolling averages
- push the predicted next month upward artificially

By excluding them, Model 3 predicts expected next-month normal spending rather than anomalous spending. This creates a correct and useful connection between Model 2 and Model 3.

## Feature Engineering

Model 3 uses feature-based monthly forecasting rather than deep sequential modeling. The feature set is designed to capture both recent spending behavior and financial context.

Key clean-spending and history features include:

- `clean_total_expense`
- `previous_month_expense`
- `expense_2_months_ago`
- `rolling_3_month_expense_avg`
- `rolling_6_month_expense_avg`
- `expense_growth_rate`

Budget and income context features include:

- `total_income`
- `expense_to_income_ratio`
- `budget_total`
- `budget_usage_ratio`
- `budget_exceeded`

Monthly activity features include:

- `transaction_count`
- `expense_transaction_count`
- `income_transaction_count`
- `category_count`

Categorical and structural features include:

- `business_profile`
- `top_spend_category_1`
- `top_spend_category_2`
- `top_spend_category_3`
- `year`
- `month`
- `month_index`

Interpretation of major features:

- `clean_total_expense`: current month's spending after excluding unusual transactions
- `previous_month_expense`: prior clean month baseline
- `rolling_3_month_expense_avg`: short-term trend
- `rolling_6_month_expense_avg`: broader medium-term trend
- `total_income`: income context for interpreting expense behavior
- `expense_to_income_ratio`: how aggressive spending is relative to income
- `budget_total`: formal budget coverage for the month
- `budget_usage_ratio`: how heavily current clean spending consumes the budget
- `transaction_count`: general monthly activity intensity
- `category_count`: category breadth of business activity
- `top spending categories`: concentration of spending by category

Forbidden leakage-style columns are not used as predictive features, including:

- `raw_total_expense`
- `excluded_unusual_expense`
- `max_expense_amount`

This preserves the clean forecasting policy.

## Model Algorithm

Model 3 uses:

```text
RandomForestRegressor
```

ML type:

- supervised regression
- feature-based time-series forecasting

Implementation structure:

- `Pipeline`
- `DictVectorizer`
- `RandomForestRegressor`

This choice is appropriate for the current stage of BizMoneyAI because:

- the feature set is mixed numeric and categorical
- the model is easy to integrate and explain
- it performs strongly on the generated monthly dataset
- it does not require very large real historical sequences to get started

## Training Process

Training script:

```text
backend/app/ml/forecasting/train_spending_forecaster.py
```

Saved artifact:

```text
backend/app/ml/models/spending_forecaster.joblib
```

Target column:

```text
next_month_total_expense
```

Training process summary:

1. load the generated monthly dataset
2. validate that required clean-spending columns exist
3. verify that forbidden raw leakage columns are not part of the feature policy
4. verify that the target aligns with next month's clean spending
5. verify that lag features are based on clean historical spending
6. perform a time-ordered train/test split
7. train the `RandomForestRegressor`
8. save the artifact with feature columns, target column, metadata, and metrics

The training artifact stores:

- the trained model
- the feature column list
- clean-spending feature metadata
- forbidden feature metadata
- dataset and split metadata
- evaluation metrics

## Validation and Evaluation

Validation script:

```text
backend/app/ml/forecasting/validate_spending_forecaster.py
```

The validation process checks:

- artifact load safety
- feature column contract consistency
- absence of forbidden leakage columns
- clean target correctness
- regression metric output
- example predictions
- sanity examples such as stable spending, increasing spending, budget-heavy behavior, and users with excluded unusual expense

Latest recorded metrics:

- R2: `0.9105`
- MAE: `1460.1375`
- RMSE: `2304.8601`
- MAPE: `0.115`

Interpretation:

- the model explains a large share of the variance in the generated validation dataset
- average error is meaningful but still practical for planning-style guidance
- performance is encouraging for a v1 forecasting model trained on generated business-finance data

These results should still be interpreted as validation on generated data rather than proof of guaranteed real-world forecast accuracy.

## Backend Integration

Runtime service:

```text
backend/app/services/spending_forecaster.py
```

Key service responsibilities:

- load the trained artifact safely
- report whether the model is ready
- aggregate monthly clean-spending history for a user
- exclude unusual transactions identified by Model 2
- build feature rows consistent with the artifact
- return safe fallback responses when history is too short or the artifact is unavailable

Structured response fields include:

- `predicted_next_month_expense`
- `confidence_level`
- `model_name`
- `months_used`
- `current_month_expense`
- `previous_month_expense`
- `rolling_3_month_expense_avg`
- `budget_total`
- `forecast_vs_budget`
- `top_reduction_categories`
- `recommendation`

The service is designed to fail safely rather than crash user flows.

## API Endpoint

Authenticated API endpoint:

```text
GET /ml/forecast-spending
```

This endpoint returns the per-user forecast for the currently logged-in user using real runtime data. If the model is unavailable or the user does not have enough clean history, the API returns a safe unavailable response rather than a server error.

This makes the endpoint stable and suitable for frontend dashboard use.

## Dashboard Integration

Model 3 is integrated into the user frontend through the dashboard forecast card.

Frontend integration:

- user dashboard forecast card
- title: **Predicted Next-Month Spending**

Displayed elements include:

- predicted next-month expense
- confidence level
- current month expense
- budget total
- forecast vs budget
- recommendation text

The dashboard also includes loading and error-safe behavior so the page does not crash if the endpoint is unavailable.

## AI Insight Recommendation

When forecasted spending exceeds budget, Model 3 can surface recommendation text and optionally persist a forecast-risk AI insight.

AIInsight rule id:

```text
ml_spending_forecast_risk
```

Current user-facing recommendation example:

> Your forecasted spending for next month may exceed your budget. Consider reducing Marketing and Software expenses.

This recommendation is designed to remain simple, explainable, and useful. It does not expose internal ML implementation details.

## Admin Visibility

Lightweight admin visibility has been added for forecast risk using persisted AI insights only.

Admin visibility includes:

- forecast risk insight count
- count of users with forecast risk
- recent forecast risk warning and critical insights

Important implementation choice:

- the admin dashboard does **not** call the forecasting model for every user on every load
- it reads persisted `ml_spending_forecast_risk` AI insights instead

This keeps the admin experience lightweight and operationally safe.

## Advantages

Model 3 provides several strong practical advantages:

- predicts expected next-month normal spending rather than only reporting historical totals
- integrates directly with budgets and recommendations
- uses real database history at runtime
- excludes unusual transactions so abnormal spikes do not distort the forecast
- fits cleanly into the existing BizMoneyAI backend and AI insight architecture
- supports both user-facing and admin-facing visibility

## Limitations

Current limitations include:

- training and validation use generated data because the app does not yet have enough real long-term user history
- the forecast is an estimate, not a guarantee
- users with short clean histories receive low-confidence or unavailable forecasts
- v1 forecasts total next-month spending rather than category-level future spending
- generated-data validation cannot fully replace future evaluation on real production behavior

## Future Work

Recommended next steps:

- category-level spending forecasting
- user feedback loops on forecast usefulness
- confidence calibration improvements
- stronger seasonality modeling
- more refined business-segment modeling
- integration with a Smart Budget Recommender
- eventual retraining on real production history once sufficient data exists

## Conclusion

Model 3 Spending Forecaster is the final forecasting component currently implemented in BizMoneyAI for next-month spending estimation.

It uses `RandomForestRegressor`, monthly clean-spending features, generated BizMoneyAI-style training data, and real database transaction history at runtime. Most importantly, it excludes unusual transactions already flagged by Model 2 so abnormal spikes do not distort normal spending forecasts.

The resulting system is practical, explainable, and product-integrated:

- trained and validated
- served through the backend API
- visible in the user dashboard
- connected to AI insight recommendations
- visible to admins through persisted forecast-risk insights

This is the correct final academic and project-level description of BizMoneyAI Model 3 in its current state.

## Report Input for ChatGPT

### Project Summary

- Project: BizMoneyAI
- Model: Model 3 Spending Forecaster
- Goal: predict expected next-month normal spending
- Algorithm: `RandomForestRegressor`
- ML type: supervised regression / feature-based time-series forecasting

### Dataset and Training Facts

- Dataset path: `backend/data/processed/bizmoneyai_spending_forecast.csv`
- Rows: `14000`
- Target: `next_month_total_expense`
- Artifact: `backend/app/ml/models/spending_forecaster.joblib`
- Training script: `backend/app/ml/forecasting/train_spending_forecaster.py`
- Validation script: `backend/app/ml/forecasting/validate_spending_forecaster.py`

### Runtime and Integration Facts

- Service: `backend/app/services/spending_forecaster.py`
- Endpoint: `GET /ml/forecast-spending`
- Dashboard integration: user dashboard forecast card
- AIInsight rule id: `ml_spending_forecast_risk`

### Model 2 Exclusion Rule

- Exclude `AIInsight.rule_id = ml_unusual_transaction`
- Only when severity is `warning` or `critical`
- Reason: unusual or fraud-like transactions should not distort normal spending forecasts

### Performance Facts

- R2: `0.9105`
- MAE: `1460.1375`
- RMSE: `2304.8601`
- MAPE: `0.115`

### Testing and Build Facts

- Backend tests: `29 passed`
- User frontend build: passed
- Admin frontend build: passed

### Important Wording

- Do not say the model predicts fraud.
- Say it predicts expected next-month normal spending.
- Do not say the forecast is guaranteed.
- Say generated data is used for training and validation because the app is not launched with enough real user history yet.
- Say real database transactions are used at runtime.
- Say unusual and fraud-like transactions are excluded so abnormal spikes do not distort normal spending forecasts.

### Recommendation Example

`Your forecasted spending for next month may exceed your budget. Consider reducing Marketing and Software expenses.`
