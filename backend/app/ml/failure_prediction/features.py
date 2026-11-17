"""Rolling-window features for component failure-risk prediction (extension of the paper, simulator-trained)."""
from __future__ import annotations

import numpy as np
import pandas as pd

from app.ml.anomaly_detection.signal_checks import BELT_PER_RPM, check_window

CHANNELS = ["motor_rpm", "hydraulic_high_pressure", "hydraulic_low_pressure", "vibration", "temperature",
            "motor_current", "material_load", "belt_speed"]
SHORT_MIN, LONG_MIN, STRIDE_MIN = 60, 720, 30
MIN_RUNNING_ROWS = 15
FEATURE_NAMES = [
    "vib_mean", "vib_std", "vib_max", "vib_slope_h", "temp_mean", "temp_max", "temp_slope_h",
    "cur_mean", "cur_slope_h", "hp_mean", "hp_std", "lp_mean", "dp_mean", "dp_std",
    "slip", "load_mean", "rpm_mean", "running_frac",
    "vib_mean_12h", "temp_mean_12h", "cur_mean_12h", "slip_12h", "temp_slope_12h", "vib_slope_12h",
    "running_hours_24h", "rule_flags_now", "rule_flags_24h",
]


def to_minutes(df: pd.DataFrame) -> pd.DataFrame:
    d = df.set_index(pd.DatetimeIndex(pd.to_datetime(df["timestamp"], utc=True)))[CHANNELS].astype(float)
    return d.resample("1min").mean()


def _slope_per_hour(s: pd.Series) -> float:
    s = s.dropna()
    if len(s) < 8:
        return 0.0
    x = (s.index - s.index[0]).total_seconds().values / 3600.0
    if x[-1] - x[0] < 1e-6:
        return 0.0
    return float(np.polyfit(x, s.values, 1)[0])


def _window_feats(w: pd.DataFrame) -> dict | None:
    r = w[w["motor_rpm"] > 10]
    if len(r) < MIN_RUNNING_ROWS:
        return None
    slip = 1 - (r["belt_speed"] / (r["motor_rpm"] * BELT_PER_RPM)).median()
    dp = r["hydraulic_high_pressure"] - r["hydraulic_low_pressure"]
    return {
        "vib_mean": r["vibration"].mean(), "vib_std": r["vibration"].std(), "vib_max": r["vibration"].max(),
        "vib_slope_h": _slope_per_hour(r["vibration"]), "temp_mean": r["temperature"].mean(),
        "temp_max": r["temperature"].max(), "temp_slope_h": _slope_per_hour(r["temperature"]),
        "cur_mean": r["motor_current"].mean(), "cur_slope_h": _slope_per_hour(r["motor_current"]),
        "hp_mean": r["hydraulic_high_pressure"].mean(), "hp_std": r["hydraulic_high_pressure"].std(),
        "lp_mean": r["hydraulic_low_pressure"].mean(), "dp_mean": dp.mean(), "dp_std": dp.std(),
        "slip": slip, "load_mean": r["material_load"].mean(), "rpm_mean": r["motor_rpm"].mean(),
        "running_frac": len(r) / max(len(w), 1),
    }


def window_features(d: pd.DataFrame, end: pd.Timestamp, flag_hist: list[int] | None = None) -> dict | None:
    """Features for the window ending at `end` from 1-min frame `d` (past data only - no leakage)."""
    w = d.loc[end - pd.Timedelta(minutes=SHORT_MIN):end]
    f = _window_feats(w)
    if f is None:
        return None
    wl = d.loc[end - pd.Timedelta(minutes=LONG_MIN):end]
    rl = wl[wl["motor_rpm"] > 10]
    if len(rl) >= 30:
        slip_l = 1 - (rl["belt_speed"] / (rl["motor_rpm"] * BELT_PER_RPM)).median()
        f.update(vib_mean_12h=rl["vibration"].mean(), temp_mean_12h=rl["temperature"].mean(),
                 cur_mean_12h=rl["motor_current"].mean(), slip_12h=slip_l,
                 temp_slope_12h=_slope_per_hour(rl["temperature"]), vib_slope_12h=_slope_per_hour(rl["vibration"]))
    else:
        f.update(vib_mean_12h=f["vib_mean"], temp_mean_12h=f["temp_mean"], cur_mean_12h=f["cur_mean"],
                 slip_12h=f["slip"], temp_slope_12h=f["temp_slope_h"], vib_slope_12h=f["vib_slope_h"])
    d24 = d.loc[end - pd.Timedelta(hours=24):end]
    f["running_hours_24h"] = float((d24["motor_rpm"] > 10).sum() / 60.0)
    f["rule_flags_now"] = len(check_window(w))
    f["rule_flags_24h"] = int(sum(flag_hist or [])) + f["rule_flags_now"]
    return f


def build_station_windows(raw: pd.DataFrame) -> pd.DataFrame:
    """All strided windows for one station's raw readings -> DataFrame indexed by window end time."""
    d = to_minutes(raw)
    ends = d.index[(d.index.minute % STRIDE_MIN == 0)]
    rows, hist = [], []
    for e in ends:
        if e < d.index[0] + pd.Timedelta(minutes=SHORT_MIN):
            continue
        f = window_features(d, e, hist[-47:])
        hist.append(f["rule_flags_now"] if f else 0)
        if f is not None:
            f["window_end"] = e
            rows.append(f)
    out = pd.DataFrame(rows)
    return out.set_index("window_end") if len(out) else out
