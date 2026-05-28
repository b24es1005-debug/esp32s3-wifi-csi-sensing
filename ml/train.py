import numpy as np
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import train_test_split
from sklearn.metrics import classification_report
import joblib

from dataset_loader import load_activity
from features import extract_features

ACTIVITIES = {
    "empty": 0,
    "walk": 1,
    "stand": 2,
    "sit": 3,
    "wave": 4,
}

X_all = []
y_all = []

for name, label in ACTIVITIES.items():

    print(f"[INFO] Loading {name}")

    X, y = load_activity(
        f"../data/datasets/{name}",
        label
    )

    X_all.extend(X)
    y_all.extend(y)

print("[INFO] Extracting features")

X_feats = []

for window in X_all:
    feats = extract_features(window)
    X_feats.append(feats)

X_feats = np.array(X_feats)
y_all = np.array(y_all)

print("[INFO] Dataset shape:", X_feats.shape)

X_train, X_test, y_train, y_test = train_test_split(
    X_feats,
    y_all,
    test_size=0.2,
    random_state=42,
    stratify=y_all
)

print("[INFO] Training model")

clf = RandomForestClassifier(
    n_estimators=200,
    max_depth=20,
    random_state=42
)

clf.fit(X_train, y_train)

preds = clf.predict(X_test)

print(classification_report(y_test, preds))

joblib.dump(clf, "models/activity_model.pkl")

print("[INFO] Model saved")