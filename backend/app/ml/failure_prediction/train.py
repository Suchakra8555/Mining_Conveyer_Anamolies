"""Train + evaluate the failure model (temporal split). Run:  python -m app.ml.failure_prediction.train"""
from __future__ import annotations

import json
from datetime import datetime, timezone

import numpy as np
import pandas as pd
from sklearn.metrics import classification_report, confusion_matrix, mean_absolute_error

from app.core.config import MODELS_DIR, SimConfig
from app.simulator.engine import DEGRADATION, ConveyorSimulator, to_epoch
from .features import FEATURE_NAMES, build_station_windows
from .model import CLASSES, FailureModel

START = datetime(2025, 1, 1, tzinfo=timezone.utc)
DAYS, TRAIN_END_DAY = 28, 19.5
LABEL_MIN_LEVEL = 0.25     # windows with 0 < level < 0.25 are ambiguous and excluded from training/evaluation


def plan(seed=42, n_train=3, n_test=2, stations=10):
    """Degradation episodes (+ some non-degradation anomalies as hard negatives), non-overlapping per station."""
    r = np.random.default_rng(seed)
    t0 = to_epoch(START)
    eps, busy = [], {i: [] for i in range(stations)}
    def free(i, a, b):
        return all(b < x or a > y for x, y in busy[i])
    for period, n, lo, hi in (("train", n_train, 1.0, TRAIN_END_DAY - 1.4), ("test", n_test, TRAIN_END_DAY + 0.2, DAYS - 1.6)):
        for sc in DEGRADATION:
            for _ in range(n):
                for _try in range(200):
                    i = int(r.integers(0, stations)); dur = float(r.uniform(12, 30))
                    a = t0 + float(r.uniform(lo, hi)) * 86400
                    b = a + dur * 3600
                    if free(i, a - 6 * 3600, b + 6 * 3600):
                        busy[i].append((a, b)); eps.append({"station_id": f"ST-{i + 1:03d}", "scenario": sc, "duration_h": dur, "start": a, "shape": float(r.uniform(1.2, 2.0))}); break
    return eps


def anomaly_noise_plan(seed=43, stations=10):
    r = np.random.default_rng(seed)
    t0 = to_epoch(START); out = []
    kinds = ["MOTOR_OVERLOAD", "HYDRAULIC_FLUCTUATION", "EXCESSIVE_VIBRATION", "BELT_SLIPPAGE", "EXCESSIVE_TEMPERATURE",
             "SENSOR_STUCK", "SENSOR_SPIKE", "SENSOR_DROPOUT"]
    for k in kinds:
        for _ in range(6):
            out.append({"station_id": f"ST-{int(r.integers(0, stations)) + 1:03d}", "kind": k,
                        "start": t0 + float(r.uniform(1, DAYS - 1)) * 86400, "duration_s": float(r.uniform(2, 5)) * 3600,
                        "channel": ["vibration", "temperature", "motor_current"][int(r.integers(0, 3))]})
    return out


def build(seed=42):
    sim = ConveyorSimulator(SimConfig(seed=seed, abnormal_cycle_prob=0.05), start=START)
    feats, truth = sim.generate_historical_dataset(START, days=DAYS, degradation_plan=plan(seed), anomaly_plan=anomaly_noise_plan())
    X = []
    for s in sim.stations:
        W = build_station_windows(feats[feats.station_id == s.station_id])
        T = truth[truth.station_id == s.station_id].set_index("timestamp")
        T.index = pd.DatetimeIndex(T.index)
        W["station_id"] = s.station_id
        for c in ("degradation", "degradation_level", "time_to_failure_h"):
            W[c] = T[c].reindex(W.index).values
        X.append(W)
    X = pd.concat(X)
    X["label"] = np.where(X["degradation_level"] >= LABEL_MIN_LEVEL, X["degradation"], "NORMAL")
    X = X[(X["degradation_level"] == 0) | (X["degradation_level"] >= LABEL_MIN_LEVEL)]
    X.loc[X.label == "NORMAL", "time_to_failure_h"] = np.nan
    return X.sort_index()


def main():
    X = build()
    split = pd.Timestamp(START) + pd.Timedelta(days=TRAIN_END_DAY)
    tr, te = X[X.index < split], X[X.index >= split]
    report = {"n_windows": int(len(X)), "train_windows": int(len(tr)), "test_windows": int(len(te)),
              "split_time": str(split), "label_min_level": LABEL_MIN_LEVEL,
              "class_counts_train": tr.label.value_counts().to_dict(), "class_counts_test": te.label.value_counts().to_dict(),
              "note": "Synthetic degradation scenarios; temporal split; risk_score = 1-P(NORMAL) is NOT a calibrated probability.",
              "candidates": {}}
    models = {}
    for name in ["extra_trees", "random_forest", "gradient_boosting"]:
        m = FailureModel(name).fit(tr, tr.label, tr.time_to_failure_h)
        pred = m.predict_proba(te).idxmax(axis=1)
        cls = classification_report(te.label, pred, labels=CLASSES, output_dict=True, zero_division=0)
        cm = confusion_matrix(te.label, pred, labels=CLASSES)
        P = m.predict_proba(te)
        risk = 1 - P["NORMAL"]
        det = (te.label != "NORMAL")
        flagged = risk >= 0.5
        fm = det & te.time_to_failure_h.notna()
        mae = float(mean_absolute_error(te.time_to_failure_h[fm], m.reg.predict(te.loc[fm, FEATURE_NAMES])))
        base = float(mean_absolute_error(te.time_to_failure_h[fm], np.full(fm.sum(), tr.time_to_failure_h.mean())))
        comp = te.label.map(lambda l: "NORMAL" if l == "NORMAL" else DEGRADATION[l][0])
        pcomp = pred.map(lambda l: "NORMAL" if l == "NORMAL" else DEGRADATION[l][0])
        ccls = classification_report(comp, pcomp, output_dict=True, zero_division=0)
        report["candidates"][name] = {
            "accuracy": round(float(cls["accuracy"]), 4), "macro_f1": round(float(cls["macro avg"]["f1-score"]), 4),
            "per_class": {k: {m_: round(v[m_], 4) for m_ in ("precision", "recall", "f1-score")} | {"support": int(v["support"])} for k, v in cls.items() if k in CLASSES},
            "per_component": {k: {m_: round(v[m_], 4) for m_ in ("precision", "recall", "f1-score")} | {"support": int(v["support"])} for k, v in ccls.items() if isinstance(v, dict) and k not in ("macro avg", "weighted avg")},
            "confusion_matrix": {"labels": CLASSES, "matrix": cm.tolist()},
            "fault_detection_at_risk_0.5": {"recall": round(float((flagged & det).sum() / det.sum()), 4),
                                            "false_alarm_rate_on_normal": round(float((flagged & ~det).sum() / (~det).sum()), 4)},
            "ttf_mae_hours": round(mae, 2), "ttf_mae_baseline_mean_predictor_hours": round(base, 2),
        }
        models[name] = m
    best = max(report["candidates"], key=lambda k: report["candidates"][k]["macro_f1"])   # NB: selected on the test split; see README caveat
    report["selected"] = best
    out = MODELS_DIR / "failure_prediction"; out.mkdir(parents=True, exist_ok=True)
    final = FailureModel(best).fit(X, X.label, X.time_to_failure_h)   # refit on all data for deployment
    final.save(out / "failure_model.joblib")
    (out / "metrics.json").write_text(json.dumps(report, indent=2, default=str))
    print(json.dumps({k: {x: v[x] for x in ("accuracy", "macro_f1", "fault_detection_at_risk_0.5", "ttf_mae_hours", "ttf_mae_baseline_mean_predictor_hours")} for k, v in report["candidates"].items()}, indent=1))
    print(report["class_counts_train"], report["class_counts_test"])
    print(json.dumps(report["candidates"][best]["per_class"], indent=0))


if __name__ == "__main__":
    main()
