"""Train + evaluate Approach 2 on simulator data (chronological split). Run:  python -m app.ml.anomaly_detection.train"""
from __future__ import annotations

import json
import time
from datetime import datetime, timezone

import numpy as np
import pandas as pd
from sklearn.metrics import confusion_matrix, f1_score, precision_recall_fscore_support

from app.core.config import MODELS_DIR, SimConfig
from app.simulator.engine import ConveyorSimulator
from .features import FEATURE_COLUMNS, extract_features, resample_station
from .pipeline import STATES, AnomalyDetector, classify_cycles

DAYS, TRAIN_DAYS = 28, 18
START = datetime(2025, 1, 1, tzinfo=timezone.utc)


def build_dataset(seed=42, days=DAYS, abnormal_prob=0.15):
    sim = ConveyorSimulator(SimConfig(seed=seed, abnormal_cycle_prob=abnormal_prob), start=START)
    feats, truth = sim.generate_historical_dataset(START, days=days)
    return sim, feats, truth


def station_frames(feats, truth, sid):
    f = extract_features(resample_station(feats[feats.station_id == sid]))
    t = truth[truth.station_id == sid].set_index("timestamp")["state_letter"].reindex(f.index)
    f["true_state"] = t.values
    return f


def match_cycles(gt: pd.DataFrame, det: list, sid: str):
    """Event-level matching: a detected cycle matches a GT cycle if their time ranges overlap."""
    rows, used = [], set()
    g = gt[gt.station_id == sid]
    for _, c in g.iterrows():
        hit = None
        for k, d in enumerate(det):
            if k in used:
                continue
            if d.start <= c["end"] and d.end >= c["start"]:
                hit = k
                break
        if hit is None:
            rows.append({"gt_kind": c["kind"], "gt_abnormal": bool(c["abnormal"]), "pred": "MISSED", "pred_category": "MISSED"})
        else:
            used.add(hit)
            d = det[hit]
            rows.append({"gt_kind": c["kind"], "gt_abnormal": bool(c["abnormal"]), "pred": d.classification, "pred_category": d.category})
    for k, d in enumerate(det):
        if k not in used:
            rows.append({"gt_kind": "NONE", "gt_abnormal": False, "pred": d.classification, "pred_category": d.category})
    return rows


def main():
    sim, feats, truth = build_dataset()
    split = pd.Timestamp(START) + pd.Timedelta(days=TRAIN_DAYS)
    train_f = feats[feats.timestamp < split]
    test_f = feats[feats.timestamp >= split]
    sids = [s.station_id for s in sim.stations]
    tr = pd.concat([station_frames(train_f, truth, s) for s in sids]).dropna(subset=["true_state"])
    te = {s: station_frames(test_f, truth, s) for s in sids}
    tr = tr[~tr["gap"]]
    gt = sim.ground_truth_cycles()
    gt_test = gt[gt["start"] >= split]

    report = {"split": str(split), "train_rows": int(len(tr)), "classifiers": {}, "note":
              "Synthetic simulator data; chronological split (first 18 days train, last 10 days test). "
              "These numbers do NOT reproduce the paper's published results."}
    best = None
    for name in ["xtree", "rf", "dt", "mlp"]:
        det = AnomalyDetector(name).fit(tr, tr["true_state"])
        y_true, y_pred, rows = [], [], []
        t0 = time.perf_counter()
        for s in sids:
            f = te[s].dropna(subset=["true_state"]).copy()
            f = f[~f["gap"]] if False else f
            f["state"] = det.predict_states(f)
            ok = ~f["gap"]
            y_true += list(f.loc[ok, "true_state"]); y_pred += list(f.loc[ok, "state"])
            cyc = classify_cycles(f, s, complete_only=True)
            rows += match_cycles(gt_test, cyc, s)
        el = time.perf_counter() - t0
        sm = f1_score(y_true, y_pred, labels=STATES, average="macro")
        r = pd.DataFrame(rows)
        gt_ab = r["gt_abnormal"]
        pr_ab = r["pred"] == "ABNORMAL"
        indet = r["pred"] == "INDETERMINATE"
        valid = ~indet & (r["pred"] != "MISSED")           # evaluable cycles
        tp = int((gt_ab & pr_ab).sum()); fp = int((~gt_ab & pr_ab).sum())
        fn = int((gt_ab & ~pr_ab & ~indet).sum()); tn = int((~gt_ab & ~pr_ab & ~indet).sum())
        prec = tp / (tp + fp) if tp + fp else 0.0
        rec = tp / (tp + fn) if tp + fn else 0.0
        f1 = 2 * prec * rec / (prec + rec) if prec + rec else 0.0
        report["classifiers"][name] = {
            "state_macro_f1": round(float(sm), 4),
            "state_confusion_matrix": {"labels": STATES, "matrix": confusion_matrix(y_true, y_pred, labels=STATES).tolist()},
            "cycle_level": {
                "n_gt_cycles": int(len(r[r.gt_kind != 'NONE'])), "n_gt_abnormal": int(gt_ab.sum()),
                "precision": round(prec, 4), "recall": round(rec, 4), "f1": round(f1, 4),
                "false_positive_rate": round(fp / (fp + tn), 4) if fp + tn else 0.0,
                "false_negative_rate": round(fn / (fn + tp), 4) if fn + tp else 0.0,
                "confusion_matrix_abnormal_vs_normal": {"tp": tp, "fp": fp, "fn": fn, "tn": tn},
                "indeterminate_data_gap": int(indet.sum()), "missed_cycles": int((r['pred'] == 'MISSED').sum()),
                "category_confusion": pd.crosstab(r["gt_kind"], r["pred_category"]).to_dict("index"),
            },
            "inference_ms_per_station_10days": round(el / len(sids) * 1000, 1),
        }
        if name == "xtree":
            best = det
    # per-inference latency for the live case (6h window of 1-min data)
    sid = sids[0]
    raw6h = feats[(feats.station_id == sid) & (feats.timestamp >= split) & (feats.timestamp < split + pd.Timedelta(hours=6))]
    from .pipeline import time_inference
    report["live_window_latency_ms_6h_window"] = round(time_inference(best, raw6h, sid), 2)
    out = MODELS_DIR / "anomaly_detection"
    out.mkdir(parents=True, exist_ok=True)
    # final model: refit on ALL data for deployment (evaluation above used the chronological split)
    all_f = pd.concat([station_frames(feats, truth, s) for s in sids]).dropna(subset=["true_state"])
    all_f = all_f[~all_f["gap"]]
    final = AnomalyDetector("xtree").fit(all_f, all_f["true_state"])
    final.save(out / "state_classifier_xtree.joblib")
    (out / "metrics.json").write_text(json.dumps(report, indent=2, default=str))
    print(json.dumps({k: v["cycle_level"] | {"state_f1": v["state_macro_f1"]} for k, v in report["classifiers"].items()}, indent=1, default=str)[:3500])


if __name__ == "__main__":
    main()
