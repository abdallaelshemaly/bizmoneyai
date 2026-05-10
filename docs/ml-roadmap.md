# BizMoneyAI ML Roadmap

## Current AI and ML Features

### Rule-based financial insights

- Endpoints: `POST /ai/generate`, `GET /ai/insights`, and `GET /ai/insights/timeseries`
- Source of truth: `backend/rules/rules.yaml`
- Runtime implementation: `backend/app/services/insights/`
- Current phase-1 rule ids are:
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
- Output is persisted as `AIInsight` records with `rule_id` and `metadata_json` so the system can audit historical insight generation later.
- Duplicate insight inserts are prevented per user, rule, period, and `scope_key`.

### Category suggestion

- Endpoint: `POST /ml/predict-category`
- Primary model approach: a local scikit-learn Pipeline saved at `backend/app/ml/models/classifier.joblib`.
- Pipeline: `TfidfVectorizer(ngram_range=(1, 2), max_features=5000)` plus `LogisticRegression(max_iter=2000)`.
- Runtime behavior: the classifier predicts a canonical category name from the transaction description, then the API returns the matching user category only after normalized or fuzzy matching.
- Matching normalizes lowercase text, trims spaces, treats `&` as `and`, collapses repeated spaces, prefers exact normalized matches, and then uses `difflib.get_close_matches`.
- The classifier has a minimum confidence threshold of `0.50`. Predictions below that threshold are ignored.
- Fallback behavior: if the model is missing, incompatible, fails, has low confidence, or predicts a category the user does not have, the API falls back to sentence-transformer embedding similarity against the user's live categories.
- There is no persisted training endpoint in the runtime API. Training is a developer command.

### Smart budget recommender

- Primary endpoint: `GET /budgets/recommendations`
- Training artifact: `backend/app/ml/models/budget_recommender.joblib`
- Training and validation scripts:
  - `backend/app/ml/budgeting/train_budget_recommender.py`
  - `backend/app/ml/budgeting/validate_budget_recommender.py`
- Runtime service: `backend/app/services/budget_recommender.py`
- Frontend surfaces:
  - `frontend/user/src/app/budgets/page.tsx`
  - `frontend/user/src/app/dashboard/page.tsx`
- Optional persisted insight rule id: `ml_budget_recommendation`
- Current status:
  - implemented
  - trained
  - validated
  - backend runtime integrated
  - API integrated
  - frontend integrated
  - optional AI insight integration implemented
  - runtime scenarios and focused backend tests passing
- Current training data source: generated BizMoneyAI-style budget data only
- Kaggle is not used for Model 4
- Current readiness statement: ready for the current project phase, with the usual limitations of synthetic training data and limited production-history coverage

## Datasets in Use

- User-owned categories.
- Synthetic classifier training data in `backend/app/ml/training/training_data.csv`.
- User transactions for current-period versus previous-period comparisons.
- User budgets for category-month budget monitoring and overspending streaks.
- Persisted `ai_insights` rows for historical review.
- YAML rule configuration maintained in `backend/rules/rules.yaml`.
- Generated BizMoneyAI-style budget recommendation data in `backend/data/processed/bizmoneyai_budget_recommender.csv`.

The supervised classifier uses the checked-in synthetic training CSV. Runtime suggestions still respect each user's own category list. A perfect synthetic split score is not evidence of real-world accuracy.

## Model Choices and Reasoning

### TF-IDF plus Logistic Regression for category prediction

Chosen because transaction descriptions are short merchant-style strings and the category set is small. The model is lightweight, local, easy to retrain, and keeps the `/ml/predict-category` contract simple.

### `all-MiniLM-L6-v2` for fallback embeddings

Kept as a fallback because it can still choose among a user's custom categories when the supervised classifier has no exact category-name match.

## Developer Commands

Run from `backend/`:

```bash
python -m app.ml.training.generate_data
python -m app.ml.training.train_model
python -c "from app.services.category_classifier import classifier; print(classifier.is_ready())"
```

### YAML rules for financial insights

Chosen because operational finance alerts need to stay transparent and easy to tune. The rules engine is easier to reason about than a black-box model at the current stage of the product.

### RandomForestRegressor plus KMeans for budget recommendations

Chosen because Model 4 currently operates on structured category-level budget features rather than raw long-sequence data. `RandomForestRegressor` works well for mixed tabular behavior features and explainable bounded recommendations, while `KMeans` adds lightweight behavior grouping for UI and AI insight context.

## Planned Next Steps

- Add an evaluation harness for category prediction quality beyond the training split report.
- Capture user correction feedback so category suggestions can improve from accepted versus rejected predictions.
- Add unusual transaction detection with Isolation Forest after the category prediction path is stable.
- Explore budget-risk scoring once there is enough historical data to evaluate those features safely.
- Retrain the smart budget recommender on real production data once enough month-by-month user history exists.
- Replace runtime default profile assumptions with real stored business-profile features if the product later captures them.
- Consider an optional process warmup step only if first-request ML latency becomes user-facing enough to justify the extra startup cost.

## Current Constraints

- If the classifier is unavailable, the route falls back to embeddings. If the sentence-transformers model is also unavailable, the embedding service falls back to deterministic random vectors to keep the API online. This preserves availability but not semantic quality.
- The current classifier dataset is synthetic, so high local accuracy should be treated as a training sanity check rather than production accuracy.
- The current classifier only returns supervised predictions when the predicted label can be safely matched to the user's categories.
- The embedding model is loaded lazily on first use. `backend/app/services/embeddings.py` already caches the model in-process after that first load, but a fresh process still pays the initial warm-start cost.
- Model 4 is trained on generated BizMoneyAI-style data because the project does not yet have enough real production budget history for direct model training.
- Model 4 runtime recommendations use real database records and exclude Model 2 unusual transactions, but recommendation quality should still improve later with real production retraining.
