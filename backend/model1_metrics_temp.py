import os
import joblib
import pandas as pd
from sklearn.model_selection import train_test_split
from sklearn.metrics import accuracy_score, f1_score, precision_score, recall_score, confusion_matrix, classification_report

DATA_PATH = "app/ml/training/training_data.csv"
MODEL_PATH = "app/ml/models/classifier.joblib"

df = pd.read_csv(DATA_PATH)
model = joblib.load(MODEL_PATH)

X_train, X_test, y_train, y_test = train_test_split(
    df["description"],
    df["category"],
    test_size=0.2,
    random_state=42,
    stratify=df["category"]
)

y_pred = model.predict(X_test)

print("MODEL 1 CATEGORY PREDICTION METRICS")
print("Samples:", len(y_test))
print("Accuracy:", round(accuracy_score(y_test, y_pred), 6))
print("Macro Precision:", round(precision_score(y_test, y_pred, average="macro", zero_division=0), 6))
print("Macro Recall:", round(recall_score(y_test, y_pred, average="macro", zero_division=0), 6))
print("Macro F1:", round(f1_score(y_test, y_pred, average="macro", zero_division=0), 6))
print("Weighted F1:", round(f1_score(y_test, y_pred, average="weighted", zero_division=0), 6))

print("\nClasses:")
print(list(model.classes_))

print("\nConfusion Matrix:")
print(confusion_matrix(y_test, y_pred, labels=model.classes_))

print("\nClassification Report:")
print(classification_report(y_test, y_pred, zero_division=0))
