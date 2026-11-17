from datetime import datetime, timezone

import numpy as np
import pandas as pd
import pytest

from app.core.config import MODELS_DIR, SimConfig
from app.ml.failure_prediction.features import FEATURE_NAMES, build_station_windows
from app.ml.failure_prediction.model import FailureModel, severity_for, CLASSES
from app.simulator.engine import ConveyorSimulator, DEGRADATION

START = datetime(2025, 1, 1, tzinfo=timezone.utc)


@pytest.fixture(scope="module")
def windows():
    sim = ConveyorSimulator(SimConfig(seed=5), start=START)
    plan = [{"station_id": "ST-001", "scenario": "bearing_degradation", "duration_h": 40, "start": START.timestamp() + 2 * 3600}]
    f, t = sim.generate_historical_dataset(START, days=3, degradation_plan=plan)
    s = f[f.station_id == "ST-001"]
    W = build_station_windows(s)
    T = t[t.station_id == "ST-001"].set_index("timestamp")
    for c in ("degradation_level", "time_to_failure_h", "degradation"):
        W[c] = T[c].reindex(W.index).values
    return W


def test_window_features_shape_and_no_label_columns(windows):
    assert set(FEATURE_NAMES) <= set(windows.columns)
    assert not (set(FEATURE_NAMES) & {"degradation", "degradation_level", "time_to_failure_h", "failure_epoch"})
    assert windows[FEATURE_NAMES].isna().sum().sum() == 0


def test_features_use_only_past_data():
    sim = ConveyorSimulator(SimConfig(seed=5, p_missing=0), start=START)
    f, _ = sim.generate_historical_dataset(START, days=2)
    s = f[f.station_id == "ST-001"]
    full = build_station_windows(s)
    cut = full.index[len(full) // 2]
    part = build_station_windows(s[s.timestamp <= cut])
    pd.testing.assert_series_equal(full.loc[cut, FEATURE_NAMES], part.loc[cut, FEATURE_NAMES], check_names=False, rtol=1e-9)


def test_degradation_is_visible_in_features(windows):
    late = windows[windows.degradation_level > 0.7]
    early = windows[windows.degradation_level == 0]
    assert late["vib_mean"].mean() > early["vib_mean"].mean() + 2
    assert late["temp_mean"].mean() > early["temp_mean"].mean() + 5


def test_temporal_split_train_and_infer(windows):
    w = windows[(windows.degradation_level >= 0.25) | (windows.degradation_level == 0)].copy()
    w["label"] = np.where(w.degradation_level >= 0.25, "bearing_degradation", "NORMAL")
    fault_idx = w.index[w.label == "bearing_degradation"]
    cut = fault_idx[len(fault_idx) // 2]            # temporal split in the middle of the fault episode
    tr, te = w[w.index < cut], w[w.index >= cut]
    assert tr.label.eq("bearing_degradation").sum() > 0 and te.label.eq("bearing_degradation").sum() > 0 and tr.index.max() < te.index.min()
    m = FailureModel("random_forest").fit(tr, tr.label, tr.time_to_failure_h)
    out = m.predict(te.head(5))
    assert {"component", "failure_type", "risk_score", "severity", "prediction_basis", "estimated_time_to_failure_hours"} <= set(out[0])
    assert all(0 <= o["risk_score"] <= 1 for o in out)
    assert out[0]["prediction_basis"] == "SIMULATED_DEGRADATION"


def test_risk_to_severity_mapping_and_class_to_component():
    assert severity_for(0.9) == "CRITICAL" and severity_for(0.7) == "HIGH" and severity_for(0.55) == "MEDIUM" and severity_for(0.1) == "LOW"
    assert DEGRADATION["belt_abrasion"][0] == "CONVEYOR_BELT" and len(CLASSES) == 8


def test_shipped_model_flags_a_clear_bearing_fault(windows):
    m = FailureModel.load(MODELS_DIR / "failure_prediction" / "failure_model.joblib")
    late = windows[windows.degradation_level > 0.8].head(3)
    healthy = windows[(windows.degradation_level == 0) & (windows.index > pd.Timestamp("2025-01-03 08:00", tz="UTC"))].head(3)   # well after the repair
    assert all(o["component"] == "BEARING" for o in m.predict(late))
    assert all(o["risk_score"] < 0.5 and o["estimated_time_to_failure_hours"] is None for o in m.predict(healthy))
