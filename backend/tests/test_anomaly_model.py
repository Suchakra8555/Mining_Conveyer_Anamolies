import numpy as np
import pandas as pd
import pytest

from app.ml.anomaly_detection.features import FEATURE_COLUMNS, extract_features, resample_station
from app.ml.anomaly_detection.pipeline import AnomalyDetector, classify_cycles, NORMAL_SEQUENCES
from app.ml.anomaly_detection.signal_checks import check_window


def _synthetic_features(states: str, speeds: list[float]):
    idx = pd.date_range("2025-01-01", periods=len(states), freq="1min", tz="UTC")
    f = pd.DataFrame({"Speed_order3": speeds, "gap": False}, index=idx)
    f["state"] = list(states)
    return f


def test_feature_extraction_columns_and_interpolation():
    idx = pd.date_range("2025-01-01", periods=20, freq="1min", tz="UTC")
    raw = pd.DataFrame({"timestamp": idx, "motor_rpm": np.arange(20.0), "hydraulic_high_pressure": 50.0, "hydraulic_low_pressure": 10.0})
    raw.loc[5, "motor_rpm"] = np.nan
    f = extract_features(resample_station(raw))
    assert set(FEATURE_COLUMNS) <= set(f.columns) and len(FEATURE_COLUMNS) == 12
    assert f["Speed"].iloc[5] == pytest.approx(5.0)          # linear interpolation of a short gap
    assert not f["gap"].any()
    assert f["Diff-pressure"].iloc[0] == 40.0


def test_long_gap_is_not_interpolated():
    idx = pd.date_range("2025-01-01", periods=30, freq="1min", tz="UTC")
    raw = pd.DataFrame({"timestamp": idx, "motor_rpm": 1.0, "hydraulic_high_pressure": 50.0, "hydraulic_low_pressure": 10.0})
    raw.loc[10:20, "motor_rpm"] = np.nan
    f = extract_features(resample_station(raw))
    assert f["gap"].any()


def _cycle(seq_states: str):
    pre, post = "BBBBBB", "BBBBBB"
    states = pre + seq_states + post
    speeds = [0.3] * len(pre) + [30.0] * len(seq_states) + [0.3] * len(post)
    return _synthetic_features(states, speeds)


def test_pattern_matching_normal():
    r = classify_cycles(_cycle("CDDDDC"), "ST-X")
    assert len(r) == 1 and r[0].classification == "NORMAL" and r[0].sequence in NORMAL_SEQUENCES


@pytest.mark.parametrize("seq,cat", [("DDDDC", "ABNORMAL_STARTUP"), ("CDDCDDC", "INTERMITTENT_OPERATION")])
def test_pattern_matching_abnormal(seq, cat):
    r = classify_cycles(_cycle(seq), "ST-X")
    assert r[0].classification == "ABNORMAL" and r[0].category == cat


def test_unexpected_stop_detected_by_missing_idle_after():
    states = "BBBBBB" + "CDDDD" + "AAAAAA"
    f = _synthetic_features(states, [0.3] * 6 + [30.0] * 5 + [0.3] * 6)
    r = classify_cycles(f, "ST-X")
    assert r[0].classification == "ABNORMAL" and r[0].category == "UNEXPECTED_STOP" and r[0].severity == "HIGH"


def test_data_gap_is_indeterminate_not_abnormal():
    f = _cycle("CDDDDC")
    f.loc[f.index[8], "gap"] = True
    assert classify_cycles(f, "ST-X")[0].classification == "INDETERMINATE"


def test_incomplete_cycle_not_classified():
    f = _synthetic_features("BBBBBB" + "CDD", [0.3] * 6 + [30.0] * 3)
    assert classify_cycles(f, "ST-X") == []


def test_operating_mode_classifier_and_inference(small_dataset):
    sim, feats, truth = small_dataset
    sid = "ST-001"
    f = extract_features(resample_station(feats[feats.station_id == sid]))
    f["true"] = truth[truth.station_id == sid].set_index("timestamp")["state_letter"].reindex(f.index).values
    f = f.dropna(subset=["true"])
    det = AnomalyDetector("xtree").fit(f.iloc[: len(f) // 2], f["true"].iloc[: len(f) // 2])
    pred = det.predict_states(f.iloc[len(f) // 2:])
    assert (pred == f["true"].iloc[len(f) // 2:].values).mean() > 0.95
    res, _ = det.detect(feats[feats.station_id == sid].iloc[len(f) // 2:], sid)
    assert res and {"station_id", "cycle_id", "sequence", "classification", "category", "severity", "detected_at"} <= set(vars(res[0]))


def test_signal_rules_flag_and_do_not_flag():
    n = 30
    base = pd.DataFrame({"motor_rpm": 45.0, "belt_speed": 4.0, "vibration": 2.0, "temperature": 55.0, "material_load": 800.0,
                         "hydraulic_high_pressure": 95.0 + np.random.default_rng(0).normal(0, 0.8, n)})
    assert check_window(base) == []
    slip = base.assign(belt_speed=3.4)
    assert [x["anomaly_type"] for x in check_window(slip)] == ["BELT_SLIPPAGE"]
    assert check_window(base.assign(motor_rpm=0.4)) == []     # idle rows are not evaluated
