"""uint8 input quantisation of the state classifier (the paper's microcontroller variant stores features as uint8).

Features are min-max scaled (clipped) to [0,1] and rounded to 0..255 integers before the tree ensemble sees them, both at
training and inference time. Trees only need threshold comparisons, so a uint8 model needs no floating point features.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.preprocessing import MinMaxScaler

from .features import FEATURE_COLUMNS
from .pipeline import AnomalyDetector


class QuantizedDetector(AnomalyDetector):
    """AnomalyDetector whose classifier is trained and queried on uint8-quantised features."""

    def _q(self, X: np.ndarray) -> np.ndarray:
        return np.rint(np.clip(self.scaler.transform(X), 0, 1) * 255).astype(np.uint8)

    def fit(self, X: pd.DataFrame, y_letters: pd.Series):
        self.scaler.fit(X[FEATURE_COLUMNS].values)
        self.clf.fit(self._q(X[FEATURE_COLUMNS].values).astype(np.float32), y_letters.values)
        self.fitted = True
        return self

    def predict_states(self, feats: pd.DataFrame) -> np.ndarray:
        from scipy.signal import medfilt
        from .pipeline import CODE, STATES
        X = self._q(feats[FEATURE_COLUMNS].fillna(0.0).values).astype(np.float32)
        raw = self.clf.predict(X)
        sm = medfilt(np.array([CODE[s] for s in raw], dtype=float), 3).astype(int)
        return np.array([STATES[i] for i in sm])
