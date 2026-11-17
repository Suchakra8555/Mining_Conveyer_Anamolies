"""Research Approach 2: supervised operating-state classifier + speed-threshold duty-cycle detector +
median filtering + state-transition extraction + pattern matching (Normal / Abnormal cycle).

Deviations from the official code (all documented in research/methodology.md):
 * simulator data instead of the confidential industrial data; speed threshold kept at 2.5 (calibrated to simulator idle noise);
 * class_weight='balanced' instead of SMOTE/undersampling; fixed hyper-parameters from the paper's grid instead of GridSearchCV;
 * data gaps inside/around a cycle give INDETERMINATE (the paper marks them abnormal) - missing data is not equipment failure;
 * the non-repeated state sequence is stripped of leading/trailing A/B (3-sample smoothing leaks idle rows into the cycle edges);
 * extra rule-based *category* and *severity* on top of the paper's binary label.
"""
from __future__ import annotations

import time
from dataclasses import dataclass

import joblib
import numpy as np
import pandas as pd
from scipy.signal import medfilt
from sklearn.ensemble import ExtraTreesClassifier, RandomForestClassifier
from sklearn.neural_network import MLPClassifier
from sklearn.preprocessing import MinMaxScaler
from sklearn.tree import DecisionTreeClassifier

from .features import FEATURE_COLUMNS, extract_features, resample_station

STATES = ["A", "B", "C", "D"]            # A off, B idle, C transition, D steady operation
CODE = {s: i for i, s in enumerate(STATES)}
SPEED_THRESHOLD = 2.5                    # rpm, duty-cycle detection (applied to Speed_order3)
NORMAL_SEQUENCES = ("CDC", "CD")
EXTRA = 3                                # minutes inspected before/after a detected cycle


def make_classifier(name: str, seed: int = 42):
    if name == "xtree":
        return ExtraTreesClassifier(n_estimators=25, max_depth=10, random_state=seed, class_weight="balanced")
    if name == "rf":
        return RandomForestClassifier(n_estimators=25, max_depth=10, random_state=seed, class_weight="balanced")
    if name == "dt":
        return DecisionTreeClassifier(max_depth=10, min_samples_split=10, random_state=seed, class_weight="balanced")
    if name == "mlp":
        return MLPClassifier(hidden_layer_sizes=(16,), max_iter=300, random_state=seed)
    raise ValueError(name)


@dataclass
class CycleResult:
    station_id: str
    cycle_id: str
    start: pd.Timestamp
    end: pd.Timestamp
    sequence: str
    classification: str      # NORMAL | ABNORMAL | INDETERMINATE
    category: str            # NONE | UNEXPECTED_STOP | ABNORMAL_STARTUP | INTERMITTENT_OPERATION | OTHER_SEQUENCE | DATA_GAP
    severity: str
    detected_at: pd.Timestamp


class AnomalyDetector:
    def __init__(self, classifier: str = "xtree", seed: int = 42):
        self.name = classifier
        self.scaler = MinMaxScaler(clip=True)
        self.clf = make_classifier(classifier, seed)
        self.fitted = False

    # ---- training (state classifier only; duty-cycle detection & pattern matching are rule-based)
    def fit(self, X: pd.DataFrame, y_letters: pd.Series):
        Xs = self.scaler.fit_transform(X[FEATURE_COLUMNS].values)
        self.clf.fit(Xs, y_letters.values)
        self.fitted = True
        return self

    def predict_states(self, feats: pd.DataFrame) -> np.ndarray:
        X = feats[FEATURE_COLUMNS].fillna(0.0).values
        raw = self.clf.predict(self.scaler.transform(X))
        codes = np.array([CODE[s] for s in raw], dtype=float)
        sm = medfilt(codes, 3).astype(int)           # 3-sample median filter as in the paper
        return np.array([STATES[i] for i in sm])

    # ---- inference on one station's raw readings
    def detect(self, readings: pd.DataFrame, station_id: str, complete_only: bool = True) -> tuple[list[CycleResult], pd.DataFrame]:
        feats = extract_features(resample_station(readings))
        if len(feats) < 10:
            return [], feats
        feats["state"] = self.predict_states(feats)
        return classify_cycles(feats, station_id, complete_only), feats

    def save(self, path):
        joblib.dump({"name": self.name, "scaler": self.scaler, "clf": self.clf}, path)

    @staticmethod
    def load(path) -> "AnomalyDetector":
        d = joblib.load(path)
        m = AnomalyDetector(d["name"])
        m.scaler, m.clf, m.fitted = d["scaler"], d["clf"], True
        return m


def _category(seq: str, after_labels: list[str], before_ok: bool, after_ok: bool) -> tuple[str, str]:
    if "A" in after_labels and not after_ok:
        return "UNEXPECTED_STOP", "HIGH"
    if seq.startswith("D"):
        return "ABNORMAL_STARTUP", "MEDIUM"
    if seq.count("D") >= 2:
        return "INTERMITTENT_OPERATION", "MEDIUM"
    return "OTHER_SEQUENCE", "LOW"


def classify_cycles(feats: pd.DataFrame, station_id: str, complete_only: bool = True) -> list[CycleResult]:
    """Detect duty cycles by speed threshold, extract the non-repeated state sequence, pattern-match."""
    inc = (feats["Speed_order3"].fillna(0) > SPEED_THRESHOLD).values
    st = feats["state"].values
    gap = feats["gap"].values
    n = len(feats)
    idx = feats.index
    res: list[CycleResult] = []
    i = 0
    while i < n:
        if not inc[i]:
            i += 1
            continue
        j = i
        while j + 1 < n and inc[j + 1]:
            j += 1
        # cycle spans [i, j]
        if complete_only and (j + EXTRA >= n or i < EXTRA):   # cycle truncated by the data window (no full leading/trailing margin)
            i = j + 1
            continue
        seq = []
        for k in range(i, j + 1):
            if not seq or seq[-1] != st[k]:
                seq.append(st[k])
        seq_s = "".join(seq).strip("AB") or "".join(seq)   # drop smoothing-edge A/B; idle margins are checked separately
        lo, hi = max(i - EXTRA, 0), min(j + EXTRA, n - 1)
        has_gap = bool(gap[lo:hi + 1].any())
        before = list(st[lo:i][-2:])
        after = list(st[j + 1:hi + 1][:2])
        before_ok = "B" in before
        after_ok = "B" in after
        cid = f"{station_id}-{idx[i].strftime('%Y%m%dT%H%M')}"
        if has_gap:
            cls, cat, sev = "INDETERMINATE", "DATA_GAP", "NONE"
        elif before_ok and after_ok and seq_s in NORMAL_SEQUENCES:
            cls, cat, sev = "NORMAL", "NONE", "NONE"
        else:
            cls = "ABNORMAL"
            cat, sev = _category(seq_s, list(st[j + 1:hi + 1]), before_ok, after_ok)
        res.append(CycleResult(station_id, cid, idx[i], idx[j], seq_s, cls, cat, sev, idx[min(j + EXTRA, n - 1)]))
        i = j + 1
    return res


def time_inference(det: AnomalyDetector, readings: pd.DataFrame, station_id: str, reps: int = 5) -> float:
    t = time.perf_counter()
    for _ in range(reps):
        det.detect(readings, station_id)
    return (time.perf_counter() - t) / reps * 1000.0
