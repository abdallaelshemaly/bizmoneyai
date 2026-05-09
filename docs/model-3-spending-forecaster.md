# Model 3: Spending Forecaster

## Model Overview

BizMoneyAI Model 3 is the **Spending Forecaster**.

Its goal is to predict a user's **next-month normal spending**, not raw spending polluted by fraud, unusual transactions, or one-off spikes.

Current model summary:

- Model name: `BizMoneyAI Model 3 Spending Forecaster`
- ML type: supervised regression
- Forecasting style: feature-based time-series forecasting on monthly financial snapshots
- Algorithm: `RandomForestRegressor`

This model uses monthly financial behavior, budget context, and recent clean spending history to estimate what a user's next month of expected spending may look like.

## Why This Model Exists

BizMoneyAI should help users plan ahead, not only explain past activity.

Model 3 exists so the product can:

- estimate likely next-month spending before the month happens
- warn users when they may exceed budget soon
- support earlier budget decisions instead of only post-hoc overspending analysis

This makes BizMoneyAI more useful as a planning assistant, not just a reporting dashboard.

## Data Strategy

Model 3 uses a split strategy between training/validation and runtime:

- **training and validation** use generated BizMoneyAI-style monthly financial data
- **runtime forecasting** uses real user transaction history from the database

The most important design rule is that Model 3 forecasts **normal expected spending**.

Because of that, unusual or fraud-like spending should not distort the forecast. The runtime service excludes transactions that were already flagged by Model 2 as unusual.

Specifically, Model 3 excludes transactions linked to:

- `AIInsight.rule_id = "ml_unusual_transaction"`
- severity `warning` or `critical`

This prevents fraud or unusual spikes from polluting monthly spending aggregates and keeps the forecast aligned with clean spending behavior.

## Dataset

Training dataset:

```text
backend/data/processed/bizmoneyai_spending_forecast.csv
```

Dataset facts:

- rows: `14000`
- target column: `next_month_total_expense`
- training uses clean spending features
- `raw_total_expense` is not used as a predictive feature
- `excluded_unusual_expense` is not used as a predictive feature
- raw spike/outlier columns such as `max_expense_amount` are excluded

The dataset is structured as monthly snapshots with current-month clean features and a next-month clean spending target.

## Features

Model 3 relies on clean monthly financial features that approximate how a real business spends over time.

Core clean spending features:

- `clean_total_expense`
- `previous_month_expense`
- `expense_2_months_ago`
- `rolling_3_month_expense_avg`
- `rolling_6_month_expense_avg`
- `expense_growth_rate`
- `expense_to_income_ratio`
- `budget_usage_ratio`

Context and operational features:

- `total_income`
- `budget_total`
- `transaction_count`
- `expense_transaction_count`
- `income_transaction_count`
- `category_count`
- `budget_exceeded`
- `year`
- `month`
- `month_index`

Categorical behavior features:

- `business_profile`
- `top_spend_category_1`
- `top_spend_category_2`
- `top_spend_category_3`

Feature explanations:

- `clean_total_expense`: the current month's expense total after unusual transactions are excluded
- `previous_month_expense`: the previous month's clean expense total
- `rolling_3_month_expense_avg`: short-horizon clean spending trend
- `rolling_6_month_expense_avg`: medium-horizon clean spending trend
- `total_income`: monthly income context so spending is interpreted relative to earning behavior
- `expense_to_income_ratio`: spending intensity relative to income
- `budget_total`: total monthly budget coverage
- `budget_usage_ratio`: how aggressively clean spending is consuming budget
- `transaction_count`: how active the month was overall
- `category_count`: how broad spending activity was across categories
- `top spending categories`: categorical signals about where spending concentration is happening

These features intentionally focus on clean behavior and budget context rather than raw anomaly leakage.

## Training

Training script:

```text
backend/app/ml/forecasting/train_spending_forecaster.py
```

Saved artifact:

```text
backend/app/ml/models/spending_forecaster.joblib
```

Training implementation:

- model: `RandomForestRegressor`
- wrapper: `Pipeline` with `DictVectorizer`
- target: `next_month_total_expense`
- split style: time-ordered train/test split

Saved artifact metadata includes:

- model object
- feature column list
- target column
- forbidden feature columns
- train/test row counts
- evaluation metrics
- clean spending policy metadata

Latest recorded training metrics:

- R2: `0.9105`
- MAE: `1460.1375`
- RMSE: `2304.8601`

These metrics are strong for the generated monthly dataset, but they should still be interpreted as synthetic-data validation rather than guaranteed production accuracy.

## Runtime Integration

Runtime service:

```text
backend/app/services/spending_forecaster.py
```

API endpoint:

```text
GET /ml/forecast-spending
```

User dashboard integration:

- frontend user dashboard includes a **Predicted Next-Month Spending** card
- the card shows the forecast, confidence level, budget comparison, and recommendation text

Returned response includes:

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

Current recommendation example:

> Your forecasted spending for next month may exceed your budget. Consider reducing Marketing and Software expenses.

The recommendation stays user-facing and avoids internal ML terminology.

## Unusual Transaction Exclusion

Model 3 connects to Model 2 through persisted `AIInsight` records.

At runtime, the spending forecast service excludes transactions that are linked to:

- `AIInsight.rule_id = "ml_unusual_transaction"`
- severity `warning`
- severity `critical`

This is important for correctness.

Without that exclusion, a single suspicious or fraud-like transaction could:

- inflate current-month expense
- distort lag features
- distort rolling averages
- push the next-month forecast upward incorrectly

By filtering those transactions out of monthly aggregation, Model 3 remains a forecast of **normal expected spending** rather than anomalous or contaminated spending.

This is the key connection between Model 2 and Model 3.

## Forecast Risk Insight Integration

Model 3 also supports optional persisted forecast-risk insights using the existing `ai_insights` table.

Current rule id:

```text
ml_spending_forecast_risk
```

Behavior summary:

- created only when forecast exceeds budget by a meaningful amount
- severity is `warning` for moderate over-budget risk
- severity becomes `critical` when predicted spending reaches roughly `150%+` of budget
- duplicate insights are prevented using user, rule, forecast month, and `scope_key`

This makes forecast-based risk visible in:

- user AI insights
- admin analytics
- recent admin insight monitoring

without introducing new tables or expensive admin-side live forecasting.

## Limitations

Current limitations:

- training and validation are based on generated BizMoneyAI-style data, not production user history
- the forecast is an estimate, not a guarantee
- forecast quality improves when users have more months of usable history
- very short histories return low confidence or unavailable results
- v1 forecasts total next-month spending, not category-level future spending

## Future Work

Logical next improvements include:

- category-level forecasting
- real user feedback loops
- confidence calibration
- stronger seasonality handling
- better user segmentation
- integration with a Smart Budget Recommender

Those steps would make the model more personalized and more actionable over time.

## Conclusion

Model 3 is now implemented as a clean-spending monthly forecaster built around `RandomForestRegressor`, generated BizMoneyAI-style monthly data, real transaction-based runtime aggregation, and a strict exclusion policy for unusual transactions detected by Model 2.

That is the correct final description of the current system:

- it predicts next-month normal spending
- it avoids fraud/unusual leakage
- it is integrated into the backend API and user dashboard
- it can surface budget-risk insights without overengineering the architecture

## Report Input for ChatGPT

### Project Summary

- Project: BizMoneyAI
- Model: Model 3, Spending Forecaster
- Final model name: `BizMoneyAI Model 3 Spending Forecaster`
- Goal: predict next-month normal spending
- Algorithm: `RandomForestRegressor`
- ML type: supervised regression with feature-based monthly forecasting
- Training script: `backend/app/ml/forecasting/train_spending_forecaster.py`
- Validation script: `backend/app/ml/forecasting/validate_spending_forecaster.py`
- Runtime service: `backend/app/services/spending_forecaster.py`
- API endpoint: `GET /ml/forecast-spending`
- Artifact: `backend/app/ml/models/spending_forecaster.joblib`

### Why the Model Exists

- BizMoneyAI should help users plan ahead, not only analyze past spending.
- The forecast can warn users before they exceed budget.

### Dataset Summary

- Dataset path: `backend/data/processed/bizmoneyai_spending_forecast.csv`
- Dataset rows: `14000`
- Target column: `next_month_total_expense`
- Training uses clean monthly spending features.
- `raw_total_expense` is not used as a predictive feature.
- `excluded_unusual_expense` is not used as a predictive feature.
- `max_expense_amount` and other raw spike columns are excluded.

### Core Features

- `clean_total_expense`
- `previous_month_expense`
- `expense_2_months_ago`
- `rolling_3_month_expense_avg`
- `rolling_6_month_expense_avg`
- `expense_growth_rate`
- `expense_to_income_ratio`
- `budget_usage_ratio`
- `total_income`
- `budget_total`
- `transaction_count`
- `expense_transaction_count`
- `income_transaction_count`
- `category_count`
- `budget_exceeded`
- `business_profile`
- `top_spend_category_1`
- `top_spend_category_2`
- `top_spend_category_3`
- `year`
- `month`
- `month_index`

### Training Facts

- Model family: `bizmoneyai_spending_forecast`
- Algorithm: `RandomForestRegressor`
- Vectorization: `DictVectorizer`
- Split style: time-ordered train/test split
- Train rows: `11200`
- Test rows: `2800`
- R2: `0.9105`
- MAE: `1460.1375`
- RMSE: `2304.8601`
- Validation MAPE: `0.115`

### Runtime Integration Facts

- Service reads real DB history from transactions, categories, budgets, and ai_insights.
- Runtime excludes transactions flagged by Model 2.
- Exclusion rule: `AIInsight.rule_id = "ml_unusual_transaction"` with severity `warning` or `critical`
- API response includes forecast, confidence, budget delta, reduction categories, and recommendation
- User dashboard shows a `Predicted Next-Month Spending` card

### Insight Integration Facts

- Forecast risk rule id: `ml_spending_forecast_risk`
- Severity:
  - `warning` when forecast moderately exceeds budget
  - `critical` when predicted spending is approximately `150%+` of budget
- Metadata includes:
  - `predicted_next_month_expense`
  - `budget_total`
  - `forecast_vs_budget`
  - `confidence_level`
  - `top_reduction_categories`
  - `source = "spending_forecaster"`
- Dedup uses user, rule, forecast month, and `scope_key`

### User-Facing Recommendation Example

`Your forecasted spending for next month may exceed your budget. Consider reducing Marketing and Software expenses.`

### Limitations

- current dataset is generated
- forecast is estimated, not guaranteed
- more real history improves quality
- v1 does not forecast per-category future spending

### Future Work

- category-level forecasting
- user feedback loops
- confidence calibration
- seasonality improvements
- smart budget recommendation integration
