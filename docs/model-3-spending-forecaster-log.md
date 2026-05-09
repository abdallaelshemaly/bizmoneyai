# Model 3 Spending Forecaster Log

## Scope

This log records the final implemented scope of BizMoneyAI Model 3: Spending Forecaster.

The goal of Model 3 was to build a forecasting workflow that:

- predicts next-month normal spending
- excludes unusual transactions already detected by Model 2
- exposes the result through the backend API
- shows the forecast in the user dashboard
- optionally persists over-budget forecast risk insights
- adds lightweight admin visibility using persisted insights only

## Final Implementation Summary

Model 3 is implemented across five layers:

1. training
2. validation
3. runtime service
4. API and user dashboard visibility
5. persisted forecast-risk insight visibility

## Training Layer

Implemented file:

```text
backend/app/ml/forecasting/train_spending_forecaster.py
```

Key outcomes:

- training uses `clean_total_expense`
- historical lag features are based on clean spending
- target is `next_month_total_expense`
- raw leakage features are excluded
- model artifact is saved to:

```text
backend/app/ml/models/spending_forecaster.joblib
```

Training algorithm:

- `RandomForestRegressor`

Saved metrics:

- rows: `14000`
- train rows: `11200`
- test rows: `2800`
- R2: `0.9105`
- MAE: `1460.1375`
- RMSE: `2304.8601`

## Validation Layer

Implemented file:

```text
backend/app/ml/forecasting/validate_spending_forecaster.py
```

Validation checks:

- artifact loads safely
- artifact feature columns exist in dataset
- forbidden leakage columns are not used
- target remains clean spending based
- regression metrics are produced
- prediction samples are printed
- sanity examples are shown for:
  - stable spending user
  - increasing spending user
  - budget-heavy user
  - user with excluded unusual expense

Recorded validation metrics:

- MAE: `1460.1375`
- RMSE: `2304.8601`
- R2: `0.9105`
- MAPE: `0.115`

## Runtime Service Layer

Implemented file:

```text
backend/app/services/spending_forecaster.py
```

Implemented methods:

- `is_ready()`
- `forecast_for_user(db, user_id)`

Runtime behavior:

- loads the trained artifact safely
- aggregates monthly transaction history from the real database
- excludes unusual transactions tied to Model 2 warnings and critical insights
- builds clean-spending monthly features that match the artifact contract
- returns safe unavailable output when history is too short or model is missing

Runtime exclusion rule:

- exclude transactions linked to `AIInsight.rule_id = "ml_unusual_transaction"`
- severity must be `warning` or `critical`

This is the main correctness rule that keeps abnormal spikes from distorting the forecast.

## API Layer

Implemented endpoint:

```text
GET /ml/forecast-spending
```

Implemented in:

```text
backend/app/api/ml.py
```

Returned fields:

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

Safe behavior:

- unavailable model does not cause a 500
- too little history does not cause a 500
- recommendation remains user-facing and non-technical

## User Dashboard Layer

Implemented frontend visibility:

```text
frontend/user/src/app/dashboard/page.tsx
```

Added card:

- `Predicted Next-Month Spending`

Displayed fields:

- predicted next-month expense
- confidence level
- current month expense
- budget total
- forecast vs budget
- recommendation

Unavailable message:

`Spending forecast is unavailable until more transaction history is available.`

Over-budget message example:

`Your forecasted spending for next month may exceed your budget. Consider reducing Marketing and Software expenses.`

## Forecast-Risk Insight Layer

Implemented using the existing `ai_insights` table.

Rule id:

```text
ml_spending_forecast_risk
```

Behavior:

- insight is created when forecast exceeds budget meaningfully
- severity is `warning` for moderate overspending risk
- severity is `critical` when forecast reaches about `150%+` of budget
- duplicate insight creation is prevented on repeated dashboard refreshes

Metadata includes:

- `predicted_next_month_expense`
- `budget_total`
- `forecast_vs_budget`
- `confidence_level`
- `top_reduction_categories`
- `source = "spending_forecaster"`
- `scope_key`

Dedup behavior:

- user id
- rule id
- forecast month
- `scope_key`

## Admin Visibility Layer

Lightweight admin visibility was added using persisted `AIInsight` rows only.

Implemented files:

- `backend/app/services/admin_analytics.py`
- `backend/app/schemas/admin_panel.py`
- `frontend/admin/src/app/page.tsx`
- `frontend/admin/src/lib/types.ts`

Admin additions:

- dashboard metric: `Forecast Risk Insights`
- count of users with forecast risk
- recent forecast risk warning/critical insights in admin monitoring

Important design decision:

- admin does **not** call live forecast generation for all users on every dashboard load
- admin reads persisted `ml_spending_forecast_risk` insights instead

## Tests Added During Model 3 Work

Backend tests created or updated:

- `backend/tests/test_spending_forecaster_training.py`
- `backend/tests/test_spending_forecaster_validation.py`
- `backend/tests/test_spending_forecaster_service.py`
- `backend/tests/test_ml_spending_forecast_api.py`
- `backend/tests/test_ai_insights.py`
- `backend/tests/test_admin_api.py`

Coverage goals included:

- clean feature policy enforcement
- no forbidden leakage columns
- artifact validation
- runtime safe failure handling
- unusual transaction exclusion
- API response stability
- forecast-risk insight creation and dedup
- admin analytics visibility

## Commands Used During Model 3 Work

Training and validation:

```bash
cd backend
python -m app.ml.forecasting.train_spending_forecaster
python -m app.ml.forecasting.validate_spending_forecaster
```

Focused backend tests:

```bash
cd backend
python -m pytest tests/test_spending_forecaster_training.py -q
python -m pytest tests/test_spending_forecaster_training.py tests/test_spending_forecaster_validation.py -q
python -m pytest tests/test_spending_forecaster_service.py -q
python -m pytest tests/test_spending_forecaster_training.py tests/test_spending_forecaster_service.py -q
python -m pytest tests/test_spending_forecaster_service.py tests/test_ml_spending_forecast_api.py -q
python -m pytest tests/test_spending_forecaster_service.py tests/test_ml_spending_forecast_api.py tests/test_ai_insights.py -q
python -m pytest tests/test_admin_api.py -q
```

Compile checks:

```bash
cd backend
python -m compileall app/services/spending_forecaster.py app/api/ml.py app/schemas/ml.py
python -m compileall app/services/admin_analytics.py app/schemas/admin_panel.py
```

Frontend builds:

```bash
cd frontend/user
npm run build
```

```bash
cd frontend/admin
npm run build
```

## Final State

Model 3 is complete as a clean-spending forecasting flow for BizMoneyAI v1.

It now includes:

- trained forecasting artifact
- validation tooling
- runtime forecasting service
- authenticated API endpoint
- user dashboard visibility
- optional persisted forecast-risk insights
- lightweight admin visibility

The most important final design rule is preserved across the system:

**fraud and unusual transactions detected by Model 2 are excluded so Model 3 forecasts normal expected spending rather than distorted spending.**
