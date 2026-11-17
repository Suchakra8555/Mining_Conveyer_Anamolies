"""Component failure-risk model: classifier (fault class) + regressor (time-to-failure), simulator-trained."""
from __future__ import annotations

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import ExtraTreesClassifier, GradientBoostingRegressor, RandomForestClassifier, GradientBoostingClassifier

from app.simulator.engine import DEGRADATION
from .features import FEATURE_NAMES

CLASSES = ["NORMAL"] + list(DEGRADATION)
RISK_THRESHOLD = 0.5


def severity_for(risk: float) -> str:
    return "CRITICAL" if risk >= 0.8 else "HIGH" if risk >= 0.65 else "MEDIUM" if risk >= 0.5 else "LOW"


def make(name: str, seed=42):
    return {"extra_trees": ExtraTreesClassifier(n_estimators=200, min_samples_leaf=2, random_state=seed, class_weight="balanced"),
            "random_forest": RandomForestClassifier(n_estimators=200, min_samples_leaf=2, random_state=seed, class_weight="balanced"),
            "gradient_boosting": GradientBoostingClassifier(random_state=seed)}[name]


class FailureModel:
    def __init__(self, name="extra_trees", seed=42):
        self.name = name
        self.clf = make(name, seed)
        self.reg = GradientBoostingRegressor(random_state=seed, n_estimators=200, max_depth=3)
        self.ttf_mae_h: float | None = None

    def fit(self, X: pd.DataFrame, y: pd.Series, ttf_h: pd.Series):
        self.clf.fit(X[FEATURE_NAMES], y)
        m = (y != "NORMAL") & ttf_h.notna()
        self.reg.fit(X.loc[m, FEATURE_NAMES], ttf_h[m])
        return self

    def predict_proba(self, X: pd.DataFrame) -> pd.DataFrame:
        p = self.clf.predict_proba(X[FEATURE_NAMES])
        return pd.DataFrame(p, columns=list(self.clf.classes_), index=X.index)

    def predict(self, X: pd.DataFrame) -> list[dict]:
        """Return one dict per row: predicted class, risk score (1 - P(NORMAL); NOT a calibrated probability), TTF."""
        P = self.predict_proba(X)
        ttf = self.reg.predict(X[FEATURE_NAMES])
        out = []
        for i in range(len(X)):
            row = P.iloc[i]
            fault = row.drop("NORMAL")
            cls = fault.idxmax()
            risk = float(1.0 - row["NORMAL"])
            comp, ftype = DEGRADATION[cls]
            out.append({"scenario": cls, "component": comp, "failure_type": ftype, "risk_score": round(risk, 4),
                        "severity": severity_for(risk), "class_scores": {k: round(float(v), 4) for k, v in row.items()},
                        "estimated_time_to_failure_hours": round(float(max(ttf[i], 0.0)), 1) if risk >= RISK_THRESHOLD else None,
                        "prediction_basis": "SIMULATED_DEGRADATION"})
        return out

    def save(self, path):
        joblib.dump(self, path)

    @staticmethod
    def load(path) -> "FailureModel":
        return joblib.load(path)
