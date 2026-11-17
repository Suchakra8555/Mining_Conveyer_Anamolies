"""Train + evaluate Approach 2 with an anti-circularity protocol. Run:  python -m app.ml.anomaly_detection.train

Protocol
  * TRAIN  seed 42, days 1-14   (noise x1.0, held-out: INTERMITTENT_OPERATION cycles and SHORT_PAUSE oddities never appear)
  * VAL    seed 42, days 15-21  (chronological continuation; the ONLY place model choice is made)
  * TEST   seeds 2001, 2002 x 14 days, noise x1.5, 25 % of normal cycles carry a benign oddity, all scenario variants present
  * the deployed model is refit on TRAIN+VAL only; TEST data is never used for fitting, selection or threshold changes
"""
from __future__ import annotations

import json
import time
from datetime import datetime, timezone

import numpy as np
import pandas as pd
from sklearn.metrics import confusion_matrix, f1_score

from app.core.config import MODELS_DIR, SimConfig
from app.simulator.engine import ConveyorSimulator, SEV_MAG, VALUE_ANOMALY_KINDS, to_epoch
from .features import FEATURE_COLUMNS, extract_features, resample_station
from .pipeline import STATES, AnomalyDetector, classify_cycles
from .signal_checks import check_window

START = datetime(2025, 1, 1, tzinfo=timezone.utc)
HELD_OUT_KIND, HELD_OUT_BENIGN = "INTERMITTENT_OPERATION", "SHORT_PAUSE"


def value_plan(seed, days, n_each=2, stations=10):
    r = np.random.default_rng(seed + 777)
    t0 = to_epoch(START); out = []
    for k in VALUE_ANOMALY_KINDS:
        for sev in ("LOW", "MEDIUM", "HIGH"):
            for _ in range(n_each):
                out.append({"station_id": f"ST-{int(r.integers(0, stations)) + 1:03d}", "kind": k, "severity": sev,
                            "start": t0 + float(r.uniform(1, days - 1)) * 86400, "duration_s": 3 * 3600})
    return out


def build(seed, days, noise, benign, held_out=False, abnormal=0.15, with_value=False):
    cfg = SimConfig(seed=seed, abnormal_cycle_prob=abnormal, benign_prob=benign, noise_scale=noise,
                    held_out_cycle_kinds=(HELD_OUT_KIND,) if held_out else (), held_out_benign=(HELD_OUT_BENIGN,) if held_out else ())
    sim = ConveyorSimulator(cfg, start=START)
    feats, truth = sim.generate_historical_dataset(START, days=days, anomaly_plan=value_plan(seed, days) if with_value else None)
    return sim, feats, truth


def frames(feats, truth, sids):
    out = {}
    for sid in sids:
        f = extract_features(resample_station(feats[feats.station_id == sid]))
        t = truth[truth.station_id == sid].set_index("timestamp")
        t.index = pd.DatetimeIndex(t.index)
        f["true_state"] = t["state_letter"].reindex(f.index).values
        out[sid] = f
    return out


def match_cycles(gt, det, sid):
    rows, used = [], set()
    for _, c in gt[gt.station_id == sid].iterrows():
        hit = next((k for k, d in enumerate(det) if k not in used and d.start <= c["end"] and d.end >= c["start"]), None)
        base = {"gt_kind": c["kind"], "gt_severity": c["severity"] or "-", "gt_variant": c["variant"] or "-", "gt_abnormal": bool(c["abnormal"])}
        if hit is None:
            rows.append({**base, "pred": "MISSED", "pred_category": "MISSED"})
        else:
            used.add(hit); d = det[hit]
            rows.append({**base, "pred": d.classification, "pred_category": d.category})
    for k, d in enumerate(det):
        if k not in used:
            rows.append({"gt_kind": "NONE", "gt_severity": "-", "gt_variant": "-", "gt_abnormal": False, "pred": d.classification, "pred_category": d.category})
    return rows


def eval_cycles(det, fr, gt, sids):
    rows, y_t, y_p = [], [], []
    for s in sids:
        f = fr[s].dropna(subset=["true_state"]).copy()
        f["state"] = det.predict_states(f)
        ok = ~f["gap"]
        y_t += list(f.loc[ok, "true_state"]); y_p += list(f.loc[ok, "state"])
        rows += match_cycles(gt, classify_cycles(f, s, True), s)
    r = pd.DataFrame(rows)
    return r, f1_score(y_t, y_p, labels=STATES, average="macro"), confusion_matrix(y_t, y_p, labels=STATES)


def summarise(r: pd.DataFrame) -> dict:
    ab = r.gt_abnormal; pab = r.pred == "ABNORMAL"; ind = r.pred == "INDETERMINATE"
    tp = int((ab & pab).sum()); fp = int((~ab & pab).sum()); fn = int((ab & ~pab & ~ind).sum()); tn = int((~ab & ~pab & ~ind).sum())
    p = tp / (tp + fp) if tp + fp else 0.0; rc = tp / (tp + fn) if tp + fn else 0.0
    rec = lambda m: (round(float((m & pab).sum() / m.sum()), 3), int(m.sum())) if m.sum() else None
    normal = ~ab & (r.gt_kind != "NONE")
    return {"precision": round(p, 4), "recall": round(rc, 4), "f1": round(2 * p * rc / (p + rc), 4) if p + rc else 0.0,
            "false_positive_rate": round(fp / (fp + tn), 4) if fp + tn else 0.0, "false_negative_rate": round(fn / (fn + tp), 4) if fn + tp else 0.0,
            "confusion": {"tp": tp, "fp": fp, "fn": fn, "tn": tn}, "n_cycles": int(len(r)), "n_abnormal": int(ab.sum()),
            "recall_by_scenario": {k: rec(ab & (r.gt_kind == k)) for k in sorted(r.gt_kind[ab].unique())},
            "recall_by_severity": {k: rec(ab & (r.gt_severity == k)) for k in ("LOW", "MEDIUM", "HIGH")},
            "recall_by_scenario_and_severity": {f"{k}/{s}": rec(ab & (r.gt_kind == k) & (r.gt_severity == s)) for k in sorted(r.gt_kind[ab].unique()) for s in ("LOW", "MEDIUM", "HIGH")},
            "false_positive_rate_by_benign_variant": {v: (round(float((normal & (r.gt_variant == v) & pab).sum() / (normal & (r.gt_variant == v)).sum()), 3), int((normal & (r.gt_variant == v)).sum()))
                                                      for v in ("-", "SLOW_STARTUP", "SHORT_PAUSE", "LOAD_SPIKE") if (normal & (r.gt_variant == v)).sum()},
            "indeterminate_data_gap": int(ind.sum()), "missed_cycles": int((r.pred == "MISSED").sum())}


def eval_value_rules(feats, truth, sids, stride_min=30):
    """Rule checks on sliding 30-min windows. Recall per (kind, severity) = windows fully inside an injected anomaly that fire the right rule."""
    hit, tot, norm_fire, norm_tot = {}, {}, 0, 0
    for sid in sids:
        f = feats[feats.station_id == sid].set_index("timestamp"); t = truth[truth.station_id == sid].set_index("timestamp")
        t = t.reindex(f.index)
        ends = f.index[(f.index.minute % stride_min == 0)][2:]
        for e in ends:
            w = f.loc[e - pd.Timedelta(minutes=30):e].reset_index(); tw = t.loc[e - pd.Timedelta(minutes=30):e]
            kinds = set(tw["anomaly_kind"]) - {""}; fired = {x["anomaly_type"] for x in check_window(w)}
            if len(kinds) == 1 and (tw["anomaly_kind"] != "").mean() > 0.99:
                k = next(iter(kinds)); sev = tw["anomaly_severity"].iloc[-1]
                tot[(k, sev)] = tot.get((k, sev), 0) + 1; hit[(k, sev)] = hit.get((k, sev), 0) + int(k in fired)
            elif not kinds and (tw["degradation_level"] == 0).all() and (tw["sensor_fault"] == "").all():
                norm_tot += 1; norm_fire += int(bool(fired))
    return {"recall_by_kind_and_severity": {f"{k}/{s}": (round(hit[(k, s)] / n, 3), n) for (k, s), n in sorted(tot.items())},
            "false_alarm_rate_on_normal_windows": (round(norm_fire / max(norm_tot, 1), 4), norm_tot)}


def diagnostics(tr, te_fr, det_state_f1):
    """Near-1.0 checks: (1) shuffled-label control, (2) trivial speed-threshold baseline, (3) leakage columns."""
    from sklearn.ensemble import ExtraTreesClassifier
    rng = np.random.default_rng(0)
    y = tr["true_state"].values.copy(); rng.shuffle(y)
    d = AnomalyDetector("xtree").fit(tr, pd.Series(y, index=tr.index))
    te = pd.concat([f.dropna(subset=["true_state"]) for f in te_fr.values()]); te = te[~te["gap"]]
    shuf = f1_score(te["true_state"], d.predict_states(te), labels=STATES, average="macro")
    sp = te["Speed_order3"].fillna(0)
    trivial = np.where(sp < 0.05, "A", np.where(sp < 2.5, "B", np.where(sp < 35, "C", "D")))
    triv = f1_score(te["true_state"], trivial, labels=STATES, average="macro")
    return {"shuffled_label_state_macro_f1": round(float(shuf), 3), "trivial_speed_threshold_state_macro_f1": round(float(triv), 3),
            "feature_columns_contain_truth": bool(set(FEATURE_COLUMNS) & {"true_state", "mode", "cycle_kind", "state_letter"})}


def main():
    t0 = time.time()
    sim, feats, truth = build(42, 21, 1.0, 0.10, held_out=True)
    sids = [s.station_id for s in sim.stations]
    gt = sim.ground_truth_cycles()
    cut = pd.Timestamp(START) + pd.Timedelta(days=14)
    fr = frames(feats, truth, sids)
    tr = pd.concat([f[f.index < cut] for f in fr.values()]).dropna(subset=["true_state"]); tr = tr[~tr["gap"]]
    va = {s: f[f.index >= cut] for s, f in fr.items()}
    gt_va = gt[gt["start"] >= cut]
    report = {"protocol": __doc__, "note": "All results are on SYNTHETIC simulator data. They measure this pipeline only and are NOT comparable to the paper's published numbers.", "validation": {}, "test": {}}
    best, best_f1 = None, -1
    for name in ["xtree", "rf", "dt", "mlp"]:
        d = AnomalyDetector(name).fit(tr, tr["true_state"])
        r, sf1, _ = eval_cycles(d, va, gt_va, sids)
        sm = summarise(r); report["validation"][name] = {"state_macro_f1": round(float(sf1), 4), "abnormal_f1": sm["f1"], "recall": sm["recall"], "fpr": sm["false_positive_rate"]}
        if sm["f1"] > best_f1:
            best, best_f1 = name, sm["f1"]
    report["selected_on_validation"] = best
    allf = pd.concat(fr.values()).dropna(subset=["true_state"]); allf = allf[~allf["gap"]]
    final = AnomalyDetector(best).fit(allf, allf["true_state"])          # TRAIN+VAL only
    te_runs, te_all_fr = [], {}
    rows, vr = [], []
    for seed in (2001, 2002):
        s2, f2, t2 = build(seed, 14, 1.5, 0.25, held_out=False, with_value=True)
        fr2 = frames(f2, t2, sids); gt2 = s2.ground_truth_cycles()
        r, sf1, cm = eval_cycles(final, fr2, gt2, sids)
        r["seed"] = seed; rows.append(r); te_runs.append((sf1, cm)); te_all_fr.update({f"{seed}-{k}": v for k, v in fr2.items()})
        vr.append(eval_value_rules(f2, t2, sids))
    R = pd.concat(rows)
    report["test"] = {"seeds": [2001, 2002], "noise_scale": 1.5, "benign_prob": 0.25, "deployed_classifier": best,
                      "state_macro_f1": [round(float(x[0]), 4) for x in te_runs], "state_confusion_matrix_seed2001": {"labels": STATES, "matrix": te_runs[0][1].tolist()},
                      "cycle_level": summarise(R), "value_rule_checks_per_seed": vr}
    report["diagnostics"] = diagnostics(tr, te_all_fr, te_runs[0][0])
    lat = []
    for _ in range(5):
        t1 = time.perf_counter(); final.detect(feats[(feats.station_id == sids[0])].iloc[:360], sids[0]); lat.append(time.perf_counter() - t1)
    report["inference_ms_per_6h_window"] = round(float(np.mean(lat)) * 1000, 2)
    out = MODELS_DIR / "anomaly_detection"; out.mkdir(parents=True, exist_ok=True)
    final.save(out / "state_classifier.joblib")
    (out / "metrics.json").write_text(json.dumps(report, indent=2, default=str))
    c = report["test"]["cycle_level"]
    print("selected", best, "| val", report["validation"])
    print("TEST", {k: c[k] for k in ("precision", "recall", "f1", "false_positive_rate", "confusion")}); print(c["recall_by_scenario"], c["recall_by_severity"]); print(c["false_positive_rate_by_benign_variant"])
    print(vr[0]["recall_by_kind_and_severity"], vr[0]["false_alarm_rate_on_normal_windows"]); print(report["diagnostics"], "state f1", report["test"]["state_macro_f1"], round(time.time() - t0), "s")


if __name__ == "__main__":
    main()
