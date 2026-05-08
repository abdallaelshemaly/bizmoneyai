# Model 2: Fraud Detection Model Using BizMoneyAI-Compatible Unusual Transaction Detection

## Problem Statement

BizMoneyAI needs a practical Model 2 that can detect unusual or risky transactions in the live SaaS product without blocking transaction creation. The model must work with the fields the application actually collects during manual transaction creation and CSV/file import, then surface useful warnings through existing AI insights, transaction views, and admin analytics.

The product goal is not autonomous fraud adjudication. The current goal is unusual transaction detection: identify transactions that look materially riskier than a user's normal business behavior and raise warning or critical alerts for review.

## Why PaySim Was Replaced

PaySim was valuable for initial experimentation because it offered a large synthetic financial dataset with labeled fraud cases. That made it useful for early exploration, backend API scaffolding, and proof-of-concept fraud workflows before BizMoneyAI had enough internal transaction history.

However, PaySim was not a good final runtime fit for BizMoneyAI. The earlier approach depended on fields such as:

- `oldbalanceOrg`
- `newbalanceOrig`
- `oldbalanceDest`
- `newbalanceDest`
- `orig_error`
- `dest_error`

Those fields do not exist in the real BizMoneyAI transaction flow. The live app creates and imports transactions using business-facing fields such as amount, type, category, description, date, and budget context. That caused a training/runtime feature mismatch: realistic suspicious rows in BizMoneyAI, such as a `45000` Marketing expense against a `4000` budget, could still be classified as normal by the PaySim-oriented model.

For that reason, PaySim is now historical background only. It should be described as initial experimentation, not as the final live Model 2 runtime implementation.

## Current Live Model

The current live implementation uses `IsolationForest` for BizMoneyAI-compatible unusual transaction detection.

This is a better fit for the current product because:

- BizMoneyAI does not yet have a reliable labeled fraud dataset from real users.
- The problem is currently closer to anomaly detection than supervised fraud classification.
- The runtime inputs are business transaction features plus application context, not mobile-money balance transition fields.

The report name can remain "Fraud Detection Model" for product/reporting purposes, but the actual live behavior is unusual/risky transaction detection using BizMoneyAI-compatible features.

## Dataset Generation

The current training data is generated as BizMoneyAI-style synthetic business transaction data, not PaySim-style balance simulation.

Generation script:

```text
backend/app/ml/anomaly/generate_bizmoneyai_fraud_data.py
```

Generated dataset path:

```text
backend/data/processed/bizmoneyai_unusual_transactions.csv
```

The generated dataset includes realistic rows with:

- `category_name`
- `amount`
- `type`
- `description`
- `date`
- `budget_amount`
- `budget_month`
- `budget_spent_before`
- `user_avg_amount`
- `category_avg_amount`
- `recent_transaction_count`
- `is_outlier`
- `expected_risk_level`

The generated data intentionally includes both:

- normal business transactions
- clear outlier patterns such as large overspends, unusual category spikes, urgent large vendor transfers, and abnormal amounts relative to budget and user/category history

This keeps training and validation aligned with what the product actually knows at runtime.

## Feature Engineering

The live detector uses the following feature columns:

- `log_amount`
- `is_expense`
- `is_income`
- `month`
- `day_of_month`
- `day_of_week`
- `has_budget`
- `budget_amount_log`
- `budget_usage_ratio`
- `amount_to_budget_ratio`
- `projected_budget_usage_ratio`
- `budget_overspend_ratio`
- `amount_to_user_avg_ratio`
- `amount_to_category_avg_ratio`
- `recent_transaction_count_30d`
- `description_urgency_score`
- `category_risk_weight`

Feature engineering is implemented in:

```text
backend/app/services/fraud_detector.py
```

The key design idea is to combine raw transaction facts with business context:

- amount size
- transaction direction (`income` or `expense`)
- calendar timing
- budget coverage and overspend
- comparison against user's prior transactions
- comparison against category history
- urgency-related description language
- category-specific risk weighting

Important examples:

- `budget_overspend_ratio` measures how far the transaction pushes projected spending beyond the category budget.
- `amount_to_user_avg_ratio` compares the transaction to the user's typical same-type transaction size.
- `amount_to_category_avg_ratio` compares the transaction to the user's historical behavior for that category.
- `description_urgency_score` increases when the description contains terms such as `urgent`, `emergency`, `wire`, `transfer`, `manual`, `override`, `offshore`, or `settlement`.

## IsolationForest Algorithm

Training script:

```text
backend/app/ml/anomaly/train_fraud_model.py
```

Saved artifact:

```text
backend/app/ml/models/fraud_detector.joblib
```

Model details:

- Model name: `BizMoneyAI Model 2 Fraud Detector`
- Model family: `bizmoneyai_unusual_transaction`
- Algorithm: `IsolationForest`
- Task type: anomaly detection / unusual transaction detection
- Runtime output: normalized risk score exposed as `fraud_probability` for API compatibility

Training parameters:

- `n_estimators=300`
- `contamination=0.04`
- `max_samples="auto"`
- `random_state=42`
- `n_jobs=-1`
- test split: `0.2`
- warning threshold: `0.50`
- critical threshold: `0.80`

The artifact stores:

- trained `IsolationForest` model
- exact feature column order
- model family metadata
- calibrated raw anomaly thresholds
- training metadata
- validation metrics

## Runtime Feature Mapping

The runtime detector no longer expects PaySim balance fields.

Instead, the backend builds the prediction payload from real BizMoneyAI transaction data and database context, including:

- current transaction amount
- transaction type
- category id and category name
- description
- transaction date
- matching budget amount for the transaction month
- budget spend before the current transaction
- budget usage ratio
- user average amount
- category average amount
- recent transaction count

This mapping is built in:

```text
backend/app/api/transactions.py
```

For manual transaction creation and import, the payload is assembled after the transaction is flushed so the system has a real transaction id and can compute historical context from the database.

## Training Process

The training process is:

1. Generate BizMoneyAI-style dataset rows.
2. Convert each row into the same engineered feature space used by the runtime detector.
3. Train `IsolationForest` on the normal subset of the data.
4. Use generated outlier rows for threshold calibration and validation.
5. Save the trained artifact and risk threshold metadata.

The model is therefore trained in a way that matches the live runtime feature contract.

Useful commands:

```powershell
cd backend
python -m app.ml.anomaly.generate_bizmoneyai_fraud_data
python -m app.ml.anomaly.train_fraud_model
python -m app.ml.anomaly.validate_fraud_detector --dataset-eval
```

## Validation Metrics

Latest dataset validation metrics for the current live implementation:

- Precision: `0.950370`
- Recall: `1.000000`
- F1-score: `0.974553`
- Confusion matrix `[[tn, fp], [fn, tp]]`: `[[4953, 47], [0, 900]]`

Latest runtime validation example:

- `45000` Marketing overspend returns `critical`

Interpretation:

- Recall is currently perfect on the generated validation dataset, meaning the generated outliers are being caught.
- Precision is strong but not perfect, which is expected for an anomaly detector intended to surface risky behavior rather than silently suppress alerts.
- These numbers are validation metrics for synthetic BizMoneyAI-style data, not proof of production-grade fraud accuracy on real customer fraud labels.

## Backend Integration

Main runtime service:

```text
backend/app/services/fraud_detector.py
```

ML API endpoint:

```text
POST /ml/detect-unusual-transaction
```

The API response shape is preserved:

- `is_unusual`
- `fraud_probability`
- `risk_level`
- `model_name`

`fraud_probability` is now a normalized anomaly risk score rather than a supervised class probability, but it stays in the same field name to preserve API compatibility.

Risk mapping:

- score `< 0.50`: `normal`
- score `>= 0.50` and `< 0.80`: `warning`
- score `>= 0.80`: `critical`

Failure behavior:

- if the model is missing, incompatible, or prediction fails, the backend returns a safe normal response
- transaction creation remains non-blocking

## Import Integration

Model 2 runs in both:

- manual transaction creation
- CSV/file import

Import endpoints:

- `POST /transactions/import-csv`
- `POST /transactions/import-file`

During import, the backend:

- parses the transaction row
- creates or finds the category
- optionally creates the month budget from `budget_amount` and `budget_month`
- creates the transaction
- runs unusual transaction detection using the saved transaction plus budget/history context
- returns the imported transaction rows including `fraud_risk_level` and `fraud_probability` when an unusual insight exists

This means suspicious imported rows are now part of the same Model 2 flow as manually created transactions.

## AIInsight Creation

When Model 2 returns `warning` or `critical`, the backend creates an `AIInsight` with:

- `rule_id = ml_unusual_transaction`
- severity `warning` or `critical`
- a transaction-scoped metadata payload

Current metadata includes:

- `transaction_id`
- `risk_level`
- `fraud_probability`
- `amount`
- `type`
- `category_id`
- `category_name`
- `budget_amount`
- `budget_month`
- `model_name`
- `scope_key`

The backend also writes a `system_log` entry with:

- event type: `unusual_transaction_detected`
- metadata containing transaction id, risk level, and probability

Duplicate protection is handled at the transaction scope so repeated processing does not create redundant unusual transaction insights for the same row.

## Frontend and Admin Visibility

The live implementation is visible across the product through existing UI surfaces.

User frontend:

- transaction responses include `fraud_risk_level`, `fraud_probability`, and `fraud_insight_id`
- the transactions page shows an `Unusual` or `Critical` badge after reload
- the insights page highlights `ml_unusual_transaction` insights

Admin visibility:

- admin analytics aggregate unusual transaction counts from `AIInsight` rows where `rule_id = ml_unusual_transaction`
- the admin dashboard shows `total_unusual_transactions`, warning/critical counts, and recent unusual transaction insights
- the admin transactions table shows the risk badge and score
- the admin logs view can filter `unusual_transaction_detected`

This reuses the existing AI insight and analytics infrastructure without introducing a new database table.

## Historical Note on PaySim

PaySim should still be mentioned in the final documentation, but only as the initial experimentation stage.

Appropriate positioning:

- PaySim helped with the first fraud-model prototype.
- It provided useful early intuition and implementation scaffolding.
- It was replaced because its balance-driven features did not match BizMoneyAI runtime inputs.
- The current live Model 2 is not the old PaySim `RandomForestClassifier`.

## Limitations

- The current model is trained and validated on generated BizMoneyAI-style synthetic data, not on real labeled fraud data from production users.
- `IsolationForest` identifies unusual patterns, but unusual does not always mean fraudulent.
- Thresholds are calibrated for a practical warning workflow and will still require tuning as real usage grows.
- Description-based urgency scoring is useful but heuristic, so it should be treated as one signal among several.
- The model is meant to support review, not to make irreversible automated fraud decisions.

## Future Work

- collect anonymized real BizMoneyAI transaction history for stronger calibration
- add feedback loops so reviewed alerts can become future labels
- improve category-specific baselines and seasonal behavior modeling
- evaluate whether separate user-segment models outperform a single shared detector
- refine threshold calibration using real user review outcomes
- expand validation against longer time windows and more realistic import scenarios

## Conclusion

The final live Model 2 implementation is a BizMoneyAI-compatible unusual transaction detector built around `IsolationForest`, synthetic business transaction data generation, runtime budget/history feature mapping, and non-blocking backend integration.

That is the correct final description of the current system. PaySim and the older `RandomForestClassifier` belong in the history of the project, not in the description of the live runtime model.

## Report Input for ChatGPT

### Project Summary

- Project: BizMoneyAI
- Model: Model 2, Fraud Detection Model
- Current implementation goal: unusual/risky transaction detection using real BizMoneyAI app fields
- Historical prototype: PaySim-based experimentation only
- Final live algorithm: `IsolationForest`
- Runtime artifact: `backend/app/ml/models/fraud_detector.joblib`
- Runtime service: `backend/app/services/fraud_detector.py`

### Problem Statement

BizMoneyAI needed a fraud/unusual transaction model that works with the application's real transaction fields and can run safely after transaction creation or import without blocking the user flow. The earlier PaySim-based prototype had a training/runtime feature mismatch because PaySim used balance transition features that BizMoneyAI does not collect. The current live model fixes that by using BizMoneyAI-compatible unusual transaction detection.

### Why PaySim Was Replaced

- PaySim was useful for early experimentation and implementation scaffolding.
- PaySim depended on balance-derived fields not present in the live BizMoneyAI app.
- That mismatch caused realistic suspicious business transactions to be underdetected.
- The final live implementation therefore replaced the PaySim `RandomForestClassifier` runtime path with an `IsolationForest` anomaly detector built on BizMoneyAI-style features.

### Dataset Summary

- Dataset type: generated BizMoneyAI-style synthetic business transaction data
- Dataset generation script: `backend/app/ml/anomaly/generate_bizmoneyai_fraud_data.py`
- Generated dataset path: `backend/data/processed/bizmoneyai_unusual_transactions.csv`
- Target column: `is_outlier`
- Includes normal rows and generated outlier rows

### Runtime Fields Used

- amount
- transaction type
- category name
- description
- date
- budget amount
- budget spent before transaction
- budget usage ratio
- user average amount
- category average amount
- recent transaction count

### Engineered Features

- `log_amount`
- `is_expense`
- `is_income`
- `month`
- `day_of_month`
- `day_of_week`
- `has_budget`
- `budget_amount_log`
- `budget_usage_ratio`
- `amount_to_budget_ratio`
- `projected_budget_usage_ratio`
- `budget_overspend_ratio`
- `amount_to_user_avg_ratio`
- `amount_to_category_avg_ratio`
- `recent_transaction_count_30d`
- `description_urgency_score`
- `category_risk_weight`

### Algorithm Summary

- Algorithm: `IsolationForest`
- Training style: anomaly detection trained on normal BizMoneyAI-style transactions
- Outlier labels are used for threshold calibration and validation, not as the core supervised training target
- Response shape remains `is_unusual`, `fraud_probability`, `risk_level`, `model_name`
- `fraud_probability` is a normalized anomaly risk score

### Training Configuration

- `n_estimators=300`
- `contamination=0.04`
- `max_samples="auto"`
- `random_state=42`
- `n_jobs=-1`
- test split: `0.2`
- warning threshold: `0.50`
- critical threshold: `0.80`

### Validation Metrics

- Precision: `0.950370`
- Recall: `1.000000`
- F1-score: `0.974553`
- Confusion matrix: `[[4953, 47], [0, 900]]`
- Runtime validation example: `45000` Marketing overspend returns `critical`

### Backend Integration Summary

- API endpoint: `POST /ml/detect-unusual-transaction`
- transaction creation runs Model 2 after the transaction is flushed
- CSV/file import also runs Model 2
- model failure does not block transaction creation
- warning and critical detections create `AIInsight` records with `rule_id = ml_unusual_transaction`
- warning and critical detections also create `system_log` entries with event type `unusual_transaction_detected`

### Frontend/Admin Visibility Summary

- user transactions page shows stored unusual transaction badges
- user insights page shows unusual transaction insights
- admin dashboard shows unusual transaction counts and recent unusual transaction insights
- admin transactions page shows transaction risk badges
- admin logs can filter `unusual_transaction_detected`

### Limitations

- current training data is synthetic
- unusual transaction detection is not the same as confirmed fraud classification
- thresholds still need ongoing calibration
- the model should support review, not replace human judgment

### Future Work

- collect real labeled review outcomes
- improve calibration and segmentation
- refine temporal and category baselines
- validate on broader real-world scenarios

### Suggested Final Position

The final report should state that Model 2 is now a BizMoneyAI-compatible unusual transaction detection system using `IsolationForest`, synthetic business transaction generation, and live runtime feature mapping based on actual SaaS transaction fields. PaySim and the earlier Random Forest approach should be presented only as historical experimentation, not as the final runtime implementation.
