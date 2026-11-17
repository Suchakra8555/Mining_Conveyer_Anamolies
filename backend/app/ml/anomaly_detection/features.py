"""Approach-2 feature extraction (mirrors `extract_features` in the official repo).

Paper channels: Speed, High-pressure, Low-pressure (+ derived differential pressure), sampled at 1 minute.
Features: raw + centred rolling means of order 3 and 5, and differential pressure for each.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

RAW = {"motor_rpm": "Speed", "hydraulic_high_pressure": "High-pressure", "hydraulic_low_pressure": "Low-pressure"}
FEATURE_COLUMNS = (
    ["Speed", "High-pressure", "Low-pressure", "Diff-pressure"]
    + [f"{c}_order{k}" for k in (3, 5) for c in ("Speed", "High-pressure", "Low-pressure", "Diff-pressure")]
)
INTERP_LIMIT = 5  # minutes: longer gaps are not interpolated (kept as gaps, never invented)


def resample_station(df: pd.DataFrame, freq: str = "1min") -> pd.DataFrame:
    """df: columns timestamp + paper sensor channels for ONE station -> regular 1-min grid, NaN where missing."""
    d = df.set_index(pd.DatetimeIndex(pd.to_datetime(df["timestamp"], utc=True)))
    d = d[list(RAW)].rename(columns=RAW).astype(float)
    d = d.resample(freq).mean()          # averaging handles both 1-min and 2-s live data
    return d


def extract_features(d: pd.DataFrame) -> pd.DataFrame:
    d = d.copy()
    for c in ("Speed", "High-pressure", "Low-pressure"):
        d[c] = d[c].interpolate("linear", limit=INTERP_LIMIT, limit_area="inside")
    d["Speed"] = d["Speed"].clip(lower=0)
    d["Diff-pressure"] = d["High-pressure"] - d["Low-pressure"]
    for k in (3, 5):
        for c in ("Speed", "High-pressure", "Low-pressure"):
            d[f"{c}_order{k}"] = d[c].rolling(k, center=True, min_periods=1).mean()
        d[f"Diff-pressure_order{k}"] = d[f"High-pressure_order{k}"] - d[f"Low-pressure_order{k}"]
    d["gap"] = d[FEATURE_COLUMNS].isna().any(axis=1)  # only gaps longer than INTERP_LIMIT remain
    return d
