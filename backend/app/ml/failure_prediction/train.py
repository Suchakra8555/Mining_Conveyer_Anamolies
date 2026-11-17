"""Train + evaluate the failure model with an anti-circularity protocol. Run:  python -m app.ml.failure_prediction.train

  * TRAIN  seed 42, episodes in days 1-15, profiles {linear, accelerating}, noise x1.0
  * VAL    seed 42, episodes in days 17-22 (purge gap of 1 day); the ONLY place the model candidate is chosen
  * TEST   seeds 2001, 2002 x 14 days, noise x1.5, benign oddities, severity-graded value anomalies as hard negatives,
           and a HELD-OUT degradation profile ("early_onset", shape 0.5) that never appears in training
  * HELD-OUT SCENARIO experiment: a model trained without belt_abrasion is asked about belt_abrasion windows
  * the deployed model is refit on TRAIN+VAL only
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

import numpy as np
import pandas as pd
from sklearn.metrics import classification_report, confusion_matrix, mean_absolute_error

from app.core.config import MODELS_DIR, SimConfig
from app.simulator.engine import DEGRADATION, VALUE_ANOMALY_KINDS, SENSOR_FAULT_KINDS, ConveyorSimulator, to_epoch
from .features import FEATURE_NAMES, build_station_windows
from .model import CLASSES, FailureModel

START = datetime(2025, 1, 1, tzinfo=timezone.utc)
LABEL_MIN_LEVEL = 0.25
PROFILES = {"linear": 1.0, "accelerating": 2.0, "early_onset": 0.5}


def episode_plan(seed, spans, profiles, stations=10):
    """spans: list of (day_lo, day_hi, n_per_scenario). One non-overlapping episode list across the spans."""
    r = np.random.default_rng(seed); t0 = to_epoch(START); eps, busy = [], {i: [] for i in range(stations)}
    free = lambda i, a, b: all(b < x or a > y for x, y in busy[i])
    for lo, hi, n in spans:
        for sc in DEGRADATION:
            for _ in range(n):
                for _try in range(300):
                    i = int(r.integers(0, stations)); dur = float(r.uniform(12, 30)); a = t0 + float(r.uniform(lo, hi - 1.3)) * 86400; b = a + dur * 3600
                    if free(i, a - 6 * 3600, b + 6 * 3600):
                        prof = profiles[int(r.integers(0, len(profiles)))]
                        busy[i].append((a, b)); eps.append({"station_id": f"ST-{i + 1:03d}", "scenario": sc, "duration_h": dur, "start": a, "shape": PROFILES[prof], "profile": prof}); break
    return eps


def negatives_plan(seed, days, stations=10):
    """Hard negatives: severity-graded value anomalies and sensor faults (labelled NORMAL for the failure model)."""
    r = np.random.default_rng(seed + 5); t0 = to_epoch(START); out = []
    for k in VALUE_ANOMALY_KINDS + ["SENSOR_STUCK", "SENSOR_SPIKE", "SENSOR_DROPOUT"]:
        for _ in range(4):
            out.append({"station_id": f"ST-{int(r.integers(0, stations)) + 1:03d}", "kind": k, "severity": ["LOW", "MEDIUM", "HIGH"][int(r.integers(0, 3))],
                        "start": t0 + float(r.uniform(1, days - 1)) * 86400, "duration_s": float(r.uniform(2, 5)) * 3600,
                        "channel": ["vibration", "temperature", "motor_current"][int(r.integers(0, 3))]})
    return out


def build(seed, days, spans, profiles, noise=1.0, benign=0.05):
    sim = ConveyorSimulator(SimConfig(seed=seed, abnormal_cycle_prob=0.05, benign_prob=benign, noise_scale=noise), start=START)
    plan = episode_plan(seed, spans, profiles)
    feats, truth = sim.generate_historical_dataset(START, days=days, degradation_plan=plan, anomaly_plan=negatives_plan(seed, days))
    prof = {(p["station_id"], p["scenario"], round(p["start"])): p["profile"] for p in plan}
    X = []
    for s in sim.stations:
        W = build_station_windows(feats[feats.station_id == s.station_id])
        T = truth[truth.station_id == s.station_id].set_index("timestamp"); T.index = pd.DatetimeIndex(T.index)
        W["station_id"] = s.station_id; W["seed"] = seed
        for c in ("degradation", "degradation_level", "time_to_failure_h"):
            W[c] = T[c].reindex(W.index).values
        X.append(W)
    X = pd.concat(X)
    ep_prof = {}
    for p in plan:   # profile per (station, scenario) episode
        ep_prof[(p["station_id"], p["scenario"])] = ep_prof.get((p["station_id"], p["scenario"]), []) + [(p["start"], p["start"] + p["duration_h"] * 3600, p["profile"])]
    def prof_of(row):
        if not row.degradation:
            return ""
        t = row.name.timestamp()
        for a, b, pr in ep_prof.get((row.station_id, row.degradation), []):
            if a <= t <= b:
                return pr
        return ""
    X["profile"] = X.apply(prof_of, axis=1)
    X["label"] = np.where(X["degradation_level"] >= LABEL_MIN_LEVEL, X["degradation"], "NORMAL")
    X = X[(X["degradation_level"] == 0) | (X["degradation_level"] >= LABEL_MIN_LEVEL)].copy()
    X.loc[X.label == "NORMAL", "time_to_failure_h"] = np.nan
    X["sev"] = pd.cut(X["degradation_level"], [-1, 0.0, 0.5, 0.75, 1.01], labels=["NONE", "LOW", "MEDIUM", "HIGH"]).astype(str)
    return X.sort_index()


def recall_table(te, pred, risk):
    out = {}
    for name, col in (("by_scenario", "label"), ("by_severity", "sev"), ("by_profile", "profile")):
        d = {}
        for k, g in te[te.label != "NORMAL"].groupby(col):
            if k in ("", "NONE"):
                continue
            idx = g.index.get_indexer_for(g.index)  # noqa
            m = te.index.isin(g.index) & (te[col] == k) & (te.label != "NORMAL")
            d[k] = {"class_recall": round(float((pred[m] == te.label[m]).mean()), 3), "flagged_recall@0.5": round(float((risk[m] >= 0.5).mean()), 3), "n": int(m.sum())}
        out[name] = d
    return out


def main():
    train = build(42, 28, [(1, 15, 3)], ["linear", "accelerating"])
    cut_val = pd.Timestamp(START) + pd.Timedelta(days=16)
    val_all = build(43, 28, [(17, 22.5, 2)], ["linear", "accelerating"])
    tr = train[train.index < cut_val]; va = val_all[val_all.index >= cut_val]
    print("train/val windows", len(tr), len(va), tr.label.value_counts().to_dict())
    tests = [build(s, 14, [(1, 13, 2)], ["linear", "accelerating", "early_onset"], noise=1.5, benign=0.25) for s in (2001, 2002)]
    te = pd.concat(tests)
    report = {"protocol": __doc__, "note": "All results are on SYNTHETIC simulator data. They measure this pipeline only and are NOT comparable to published numbers.",
              "windows": {"train": int(len(tr)), "val": int(len(va)), "test": int(len(te))}, "label_min_level": LABEL_MIN_LEVEL,
              "severity_buckets": "degradation level LOW 0.25-0.5, MEDIUM 0.5-0.75, HIGH >=0.75", "validation": {}, "test": {}}
    best, best_f1, fitted = None, -1, {}
    for name in ["extra_trees", "random_forest", "gradient_boosting"]:
        m = FailureModel(name).fit(tr, tr.label, tr.time_to_failure_h)
        pv = m.predict_proba(va).idxmax(axis=1)
        f1 = classification_report(va.label, pv, labels=CLASSES, output_dict=True, zero_division=0)["macro avg"]["f1-score"]
        report["validation"][name] = {"macro_f1": round(float(f1), 4)}
        if f1 > best_f1: best, best_f1 = name, f1
    report["selected_on_validation"] = best
    trva = pd.concat([tr, va])
    final = FailureModel(best).fit(trva, trva.label, trva.time_to_failure_h)     # TRAIN+VAL only
    P = final.predict_proba(te); pred = P.idxmax(axis=1); risk = 1 - P["NORMAL"]
    cls = classification_report(te.label, pred, labels=CLASSES, output_dict=True, zero_division=0)
    det = te.label != "NORMAL"; flagged = risk >= 0.5
    fm = det & te.time_to_failure_h.notna()
    mae = float(mean_absolute_error(te.time_to_failure_h[fm], final.reg.predict(te.loc[fm, FEATURE_NAMES])))
    base = float(mean_absolute_error(te.time_to_failure_h[fm], np.full(fm.sum(), trva.time_to_failure_h.mean())))
    comp = lambda s: s.map(lambda l: "NORMAL" if l == "NORMAL" else DEGRADATION[l][0])
    ccls = classification_report(comp(te.label), comp(pred), output_dict=True, zero_division=0)
    normal_hard = ~det
    report["test"] = {"seeds": [2001, 2002], "noise_scale": 1.5, "deployed_model": best, "accuracy": round(float(cls["accuracy"]), 4), "macro_f1": round(float(cls["macro avg"]["f1-score"]), 4),
        "per_class": {k: {m_: round(v[m_], 4) for m_ in ("precision", "recall", "f1-score")} | {"support": int(v["support"])} for k, v in cls.items() if k in CLASSES},
        "per_component": {k: {m_: round(v[m_], 4) for m_ in ("precision", "recall", "f1-score")} | {"support": int(v["support"])} for k, v in ccls.items() if isinstance(v, dict) and k not in ("macro avg", "weighted avg")},
        "confusion_matrix": {"labels": CLASSES, "matrix": confusion_matrix(te.label, pred, labels=CLASSES).tolist()},
        "fault_flagged_recall@0.5": round(float((flagged & det).sum() / det.sum()), 4), "false_alarm_rate_on_normal@0.5": round(float((flagged & normal_hard).sum() / normal_hard.sum()), 4),
        "ttf_mae_hours": round(mae, 2), "ttf_mae_baseline_mean_predictor_hours": round(base, 2), **recall_table(te, pred, risk)}
    # held-out SCENARIO experiment
    keep = trva.label != "belt_abrasion"
    m2 = FailureModel(best).fit(trva[keep], trva.label[keep], trva.time_to_failure_h[keep])
    ba = te[te.label == "belt_abrasion"]; P2 = m2.predict_proba(ba); r2 = 1 - P2["NORMAL"]
    report["held_out_scenario_belt_abrasion"] = {"n_windows": int(len(ba)), "flagged_as_risk@0.5": round(float((r2 >= 0.5).mean()), 3),
                                                 "predicted_class_distribution": P2.drop(columns=["NORMAL"]).idxmax(axis=1).value_counts().to_dict()}
    out = MODELS_DIR / "failure_prediction"; out.mkdir(parents=True, exist_ok=True)
    final.save(out / "failure_model.joblib")
    (out / "metrics.json").write_text(json.dumps(report, indent=2, default=str))
    t = report["test"]
    print("selected", best, report["validation"]); print({k: t[k] for k in ("accuracy", "macro_f1", "fault_flagged_recall@0.5", "false_alarm_rate_on_normal@0.5", "ttf_mae_hours", "ttf_mae_baseline_mean_predictor_hours")})
    print(t["by_scenario"]); print(t["by_severity"]); print(t["by_profile"]); print(report["held_out_scenario_belt_abrasion"]); print(t["per_component"])


if __name__ == "__main__":
    main()
