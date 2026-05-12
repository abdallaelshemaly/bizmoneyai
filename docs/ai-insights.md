# BizMoneyAI AI Insights

## Overview

BizMoneyAI currently uses a rule-based insight engine only. The production source of truth for phase 1 is `backend/rules/rules.yaml`, and the runtime implementation lives under `backend/app/services/insights/`.

The current rule engine is modular:

- `calculator.py`: builds current-period and previous-period financial context from transactions and budgets.
- `rules.py`: loads and validates `rules.yaml`, maps rule types to evaluators, and creates in-memory insight candidates.
- `dedup.py`: prevents duplicate insight creation for the same `user_id + rule_id + period + scope_key`.
- `generator.py`: orchestrates context building, rule evaluation, deduplication, and `AIInsight` inserts.
- `backend/app/services/rules_engine.py`: compatibility wrapper used by the existing API layer.

## Persisted Insight Shape

`AIInsight` rows are stored in `ai_insights` with:

- `rule_id`: the YAML rule identifier that triggered the insight.
- `title`
- `message`
- `severity`
- `period_start`
- `period_end`
- `metadata_json`: structured trigger context such as `scope_key`, ratios, amounts, category ids, and budget month details.

Category-period rules always persist a `scope_key`. Examples:

- `category:12`
- `category:12:month:2026-04-01`

## Current Phase 1 Rules

The current production ruleset contains these YAML rule ids:

- `zero_income_with_expense`
- `expense_ratio`
- `profit_drop_percent`
- `spending_spike_percent`
- `negative_balance`
- `negative_balance_below`
- `budget_overspend_ratio`
- `category_income_ratio`
- `income_drop_percent`
- `missing_budget_high_spend`
- `consecutive_budget_overspend`

### Rule Semantics

- `zero_income_with_expense`
  Trigger: current income is less than or equal to `defaults.min_income_for_ratio_rules` and current expense is greater than `0`.
  Guard: runs only for full calendar-month selections so partial ranges do not create misleading no-income alerts.
  Scope: `period`.
- `expense_ratio`
  Trigger: `current_expense / current_income` crosses configured thresholds.
  Scope: `period`.
- `profit_drop_percent`
  Trigger: current-period profit is below previous-period profit and the drop percentage crosses thresholds.
  Guard: runs only when the selected period is a full calendar month span so the comparison uses a full comparable previous month window.
  Scope: `period`.
- `spending_spike_percent`
  Trigger: current-period expense is above previous-period expense and the increase percentage crosses thresholds.
  Scope: `period`.
- `negative_balance`
  Trigger: current-period balance is strictly less than `0`.
  Scope: `period`.
- `negative_balance_below`
  Trigger: current-period balance is less than or equal to the configured lower bound.
  Scope: `period`.
- `budget_overspend_ratio`
  Trigger: a budgeted category-month reaches the configured spend-to-budget ratio.
  Scope: `category_period`.
- `category_income_ratio`
  Trigger: one expense category reaches the configured share of total current-period income.
  Scope: `category_period`.
- `income_drop_percent`
  Trigger: current-period income is below previous-period income and the drop percentage crosses thresholds.
  Guard: runs only when the selected period is a full calendar month span so partial selections do not create misleading drop alerts.
  Scope: `period`.
- `missing_budget_high_spend`
  Trigger: a category has expense spending in a specific month but no budget for that same category-month, and the spend crosses thresholds.
  Scope: `category_period`.
- `consecutive_budget_overspend`
  Trigger: a budgeted category-month is part of an overspending streak and the streak length crosses thresholds.
  Scope: `category_period`.

## API Contract

### `POST /ai/generate`

- Optional JSON body:
  - `period_start`
  - `period_end`
- Default behavior with no body:
  - `period_end = date.today()`
  - `period_start = period_end - 30 days`
- Behavior:
  - runs the rule engine for the authenticated user
  - inserts only new insights after deduplication
  - logs a `generate_insights` event in `system_log`
  - returns the newly created `AIInsight` rows
- Validation:
  - returns `422` when `period_start > period_end`

### `GET /ai/insights`

- Query params:
  - `date_from`
  - `date_to`
  - `severity`
- Behavior:
  - returns persisted insights for the authenticated user
  - filters by `created_at` date range and severity
- Validation:
  - returns `422` when `date_from > date_to`

### `GET /ai/insights/timeseries`

- Query params:
  - `date_from`
  - `date_to`
  - `severity`
  - `granularity` = `day | month`
- Behavior:
  - returns persisted insight counts bucketed by created date
  - includes total counts plus `info`, `warning`, and `critical` counts per bucket
- Validation:
  - returns `422` when `date_from > date_to`
  - returns `422` for unsupported `granularity`

## Validation Rules For `rules.yaml`

The loader fails fast when:

- a rule id is duplicated
- a rule type is unsupported
- a severity name is unsupported
- `severity_thresholds` is empty or not a mapping
- a threshold is non-numeric
- a scope is outside `period` or `category_period`

## Verification Status

The backend rule engine and `/ai` routes are covered by isolated automated tests in:

- `backend/tests/test_ai_rules_engine.py`
- `backend/tests/test_ai_api.py`

The latest verification pass covered:

- zero-income behavior
- threshold ladders for expense ratio, budget usage, and overspending streaks
- previous-period comparison rules
- balance rules
- category-income pressure
- month-accurate missing-budget detection
- deduplication
- config validation
- API filtering, timeseries, default period, explicit period, and `422` validation
- edge cases like empty periods, missing previous periods, zero-amount budgets, malformed message templates, stable scope keys, and required metadata

Command used:

```powershell
..\.venv\Scripts\python.exe -m pytest tests\test_ai_rules_engine.py tests\test_ai_api.py -q
```

