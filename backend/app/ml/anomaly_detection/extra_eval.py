"""Approach 3 vs Approach 2, and uint8 quantisation. Same data protocol as train.py (train/val/test by seed and time,
INTERMITTENT_OPERATION and SHORT_PAUSE absent from training). Run:  python -m app.ml.anomaly_detection.extra_eval"""
from __future__ import annotations

import io
import json
import time

import joblib
import numpy as np
import pandas as pd
from sklearn.metrics import f1_score

from app.core.config import MODELS_DIR
from .approach3 import Approach3, cycle_sequences
from .pipeline import STATES, AnomalyDetector, classify_cycles
from .quantization import QuantizedDetector
from .train import START, build, eval_cycles, frames, match_cycles, summarise


def a3_rows(a3, fr, gt, sids):
    rows = []
    for s in sids:
        f = fr[s].dropna(subset=["true_state"])
        rows += match_cycles(gt, a3.detect(f, s), s)
    return pd.DataFrame(rows)


def training_sequences(det, fr, gt, sids, lo, hi):
    X, y = [], []
    for s in sids:
        f = fr[s].dropna(subset=["true_state"]); f = f[(f.index >= lo) & (f.index < hi)].copy()
        f["state"] = det.predict_states(f)                          # recognised (predicted) states, as in the paper
        g = gt[gt.station_id == s]
        for c in cycle_sequences(f):
            m = g[(g["start"] <= c["end"]) & (g["end"] >= c["start"])]
            if len(m):
                X.append(c["enc"]); y.append(int(bool(m.iloc[0]["abnormal"])))
    return np.array(X, float), np.array(y)


def short(sm):
    keys = ("precision", "recall", "f1", "false_positive_rate", "false_negative_rate", "confusion", "recall_by_scenario", "recall_by_severity", "false_positive_rate_by_benign_variant")
    return {k: sm[k] for k in keys}


def main():
    sim, feats, truth = build(42, 21, 1.0, 0.10, held_out=True)
    sids = [s.station_id for s in sim.stations]; gt = sim.ground_truth_cycles(); fr = frames(feats, truth, sids)
    t0, cut, t1 = pd.Timestamp(START), pd.Timestamp(START) + pd.Timedelta(days=14), pd.Timestamp(START) + pd.Timedelta(days=22)
    tr = pd.concat([f[f.index < cut] for f in fr.values()]).dropna(subset=["true_state"]); tr = tr[~tr["gap"]]
    allf = pd.concat(fr.values()).dropna(subset=["true_state"]); allf = allf[~allf["gap"]]
    state_tr = AnomalyDetector("xtree").fit(tr, tr["true_state"])
    state_all = AnomalyDetector("xtree").fit(allf, allf["true_state"])
    va = {s: f[f.index >= cut] for s, f in fr.items()}; gt_va = gt[gt["start"] >= cut]
    Xtr, ytr = training_sequences(state_tr, fr, gt, sids, t0, cut)
    Xall, yall = training_sequences(state_all, fr, gt, sids, t0, t1)
    out = {"note": "SYNTHETIC data; measures the pipeline only; not comparable to the paper. Training data contains no INTERMITTENT_OPERATION and no SHORT_PAUSE.",
           "n_train_sequences": int(len(ytr)), "train_abnormal_share": round(float(ytr.mean()), 3), "validation": {}, "test": {}}
    best, bf1 = None, -1
    for name in ["rf", "dt", "xtree", "xgb", "nb", "mlp"]:
        a3 = Approach3(state_tr, name).fit(Xtr, ytr)
        sm = summarise(a3_rows(a3, va, gt_va, sids))
        out["validation"][name] = {"abnormal_f1": sm["f1"], "recall": sm["recall"], "precision": sm["precision"]}
        if sm["f1"] > bf1: best, bf1 = name, sm["f1"]
    out["approach3_selected_on_validation"] = best
    a3f = Approach3(state_all, best).fit(Xall, yall)
    rows2, rows3, qrows = [], [], {}
    qd = QuantizedDetector("xtree").fit(allf, allf["true_state"])
    tests = []
    for seed in (2001, 2002):
        s2, f2, t2 = build(seed, 14, 1.5, 0.25, held_out=False, with_value=False)
        fr2 = frames(f2, t2, sids); g2 = s2.ground_truth_cycles(); tests.append((fr2, g2, f2))
        r2, _, _ = eval_cycles(state_all, fr2, g2, sids); rows2.append(r2)
        rows3.append(a3_rows(a3f, fr2, g2, sids))
    out["test"]["approach2_rules"] = short(summarise(pd.concat(rows2)))
    out["test"][f"approach3_{best}"] = short(summarise(pd.concat(rows3)))
    # ---- quantisation
    def state_f1(det):
        yt, yp = [], []
        for fr2, g2, _ in tests:
            for s in sids:
                f = fr2[s].dropna(subset=["true_state"]).copy(); f["state"] = det.predict_states(f); ok = ~f["gap"]
                yt += list(f.loc[ok, "true_state"]); yp += list(f.loc[ok, "state"])
        return round(float(f1_score(yt, yp, labels=STATES, average="macro")), 4)
    def cyc(det):
        rr = [eval_cycles(det, fr2, g2, sids)[0] for fr2, g2, _ in tests]
        sm = summarise(pd.concat(rr)); return {k: sm[k] for k in ("precision", "recall", "f1", "false_positive_rate")}
    def size(det):
        b = io.BytesIO(); joblib.dump({"scaler": det.scaler, "clf": det.clf}, b); return len(b.getvalue())
    raw = tests[0][2]; raw = raw[raw.station_id == sids[0]].iloc[:360]
    def lat(det):
        t = time.perf_counter()
        for _ in range(10): det.detect(raw, sids[0])
        return round((time.perf_counter() - t) / 10 * 1000, 2)
    out["quantization"] = {"float32_extra_trees": {"state_macro_f1": state_f1(state_all), "cycle_level": cyc(state_all), "model_bytes": size(state_all), "latency_ms_6h_window": lat(state_all)},
                           "uint8_inputs_extra_trees": {"state_macro_f1": state_f1(qd), "cycle_level": cyc(qd), "model_bytes": size(qd), "latency_ms_6h_window": lat(qd)},
                           "note": "uint8 here quantises the INPUT FEATURES only (as in the paper's MCU variant); the tree thresholds stay float in scikit-learn, so model size is not reduced. Size/latency would need a C export to show real MCU savings."}
    d = MODELS_DIR / "anomaly_detection"
    (d / "approach3_metrics.json").write_text(json.dumps(out, indent=2, default=str))
    print(json.dumps({"val": out["validation"], "sel": best, "test_A2": {k: out["test"]["approach2_rules"][k] for k in ("precision", "recall", "f1", "false_positive_rate")},
                      "test_A3": {k: out["test"][f"approach3_{best}"][k] for k in ("precision", "recall", "f1", "false_positive_rate")},
                      "A3_scenario": out["test"][f"approach3_{best}"]["recall_by_scenario"], "A3_benign": out["test"][f"approach3_{best}"]["false_positive_rate_by_benign_variant"],
                      "A2_benign": out["test"]["approach2_rules"]["false_positive_rate_by_benign_variant"], "quant": out["quantization"]}, indent=1, default=str))


if __name__ == "__main__":
    main()
