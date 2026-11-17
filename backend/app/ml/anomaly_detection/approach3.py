"""Research Approach 3: like Approach 2, but the Normal/Abnormal decision is made by a LEARNED duty-cycle classifier.

Same state classifier and the same speed-threshold cycle detection as Approach 2. Instead of matching the state sequence
against fixed patterns ("CDC"/"CD" + idle margins), the non-repeated state sequence of each detected cycle, taken with a
3-minute margin on both sides, is label-encoded (A..D -> 1..4), zero-padded and fed to a classifier trained on cycles
labelled normal/abnormal (mirrors `find_non_consecutive_sequences` / `pad_sequences` / `train_cycle_classifier`
in the official repo).

Deviations: fixed hyper-parameters instead of GridSearchCV; classifiers rf / dt / xtree / xgb / nb / mlp; training labels
come from simulator ground truth; the category and severity are still assigned by the rule in pipeline._category because
the classifier is binary.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .pipeline import CODE, EXTRA, SPEED_THRESHOLD, CycleResult, _category, make_classifier

MAXLEN = 14
ENC = {s: i + 1 for s, i in CODE.items()}   # A..D -> 1..4, 0 = padding


def _collapse(labels) -> list[str]:
    out = []
    for x in labels:
        if not out or out[-1] != x:
            out.append(x)
    return out


def cycle_sequences(feats: pd.DataFrame, complete_only: bool = True) -> list[dict]:
    """Detected cycles (speed threshold) with their margin-extended encoded state sequence."""
    inc = (feats["Speed_order3"].fillna(0) > SPEED_THRESHOLD).values
    st, gap, n, idx = feats["state"].values, feats["gap"].values, len(feats), feats.index
    res, i = [], 0
    while i < n:
        if not inc[i]:
            i += 1
            continue
        j = i
        while j + 1 < n and inc[j + 1]:
            j += 1
        if complete_only and (j + EXTRA >= n or i < EXTRA):
            i = j + 1
            continue
        lo, hi = max(i - EXTRA, 0), min(j + EXTRA, n - 1)
        seq = _collapse(st[lo:hi + 1])
        enc = [ENC[x] for x in seq][:MAXLEN]
        enc += [0] * (MAXLEN - len(enc))
        res.append({"i": i, "j": j, "start": idx[i], "end": idx[j], "seq": "".join(seq), "enc": enc,
                    "inner": "".join(_collapse(st[i:j + 1])).strip("AB"), "gap": bool(gap[lo:hi + 1].any()),
                    "after": list(st[j + 1:hi + 1]), "detected_at": idx[min(j + EXTRA, n - 1)]})
        i = j + 1
    return res


class Approach3:
    def __init__(self, state_detector, classifier: str = "rf", seed: int = 42):
        self.state = state_detector
        self.name = classifier
        self.clf = make_classifier(classifier, seed)
        if classifier == "xgb":   # binary target for the duty-cycle classifier
            self.clf = self.clf.est

    def fit(self, X: np.ndarray, y: np.ndarray):
        self.clf.fit(np.asarray(X, float), np.asarray(y, int))      # 1 = abnormal
        return self

    def detect(self, feats: pd.DataFrame, station_id: str, complete_only: bool = True) -> list[CycleResult]:
        feats = feats.copy()
        feats["state"] = self.state.predict_states(feats)
        seqs = cycle_sequences(feats, complete_only)
        if not seqs:
            return []
        pred = self.clf.predict(np.array([s["enc"] for s in seqs], float))
        out = []
        for s, p in zip(seqs, pred):
            cid = f"{station_id}-{s['start'].strftime('%Y%m%dT%H%M')}"
            if s["gap"]:
                cls, cat, sev = "INDETERMINATE", "DATA_GAP", "NONE"
            elif int(p) == 0:
                cls, cat, sev = "NORMAL", "NONE", "NONE"
            else:
                cls = "ABNORMAL"; cat, sev = _category(s["inner"], s["after"], True, "B" in s["after"][:2])
            out.append(CycleResult(station_id, cid, s["start"], s["end"], s["inner"], cls, cat, sev, s["detected_at"]))
        return out
