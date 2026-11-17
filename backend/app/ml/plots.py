"""Evaluation figures from the saved metrics JSON files (nothing is recomputed). Run:  python -m app.ml.plots"""
from __future__ import annotations

import json

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from app.core.config import MODELS_DIR, REPO_ROOT

OUT = REPO_ROOT / "docs" / "figures"


def cm(ax, m, labels, title):
    m = np.array(m); n = m / np.maximum(m.sum(1, keepdims=True), 1)
    ax.imshow(n, cmap="Blues", vmin=0, vmax=1)
    ax.set_xticks(range(len(labels))); ax.set_yticks(range(len(labels)))
    ax.set_xticklabels([l.replace("_degradation", "").replace("_deterioration", "") for l in labels], rotation=45, ha="right", fontsize=8)
    ax.set_yticklabels([l.replace("_degradation", "").replace("_deterioration", "") for l in labels], fontsize=8)
    for i in range(len(labels)):
        for j in range(len(labels)):
            ax.text(j, i, int(m[i, j]), ha="center", va="center", fontsize=7, color="white" if n[i, j] > 0.5 else "black")
    ax.set_title(title, fontsize=10); ax.set_xlabel("predicted"); ax.set_ylabel("true")


def bars(ax, d, title, color):
    k = list(d); v = [d[x][0] if isinstance(d[x], (list, tuple)) else d[x] for x in k]
    ax.bar(k, v, color=color); ax.set_ylim(0, 1.05); ax.set_title(title, fontsize=10)
    ax.tick_params(axis="x", rotation=30, labelsize=8)
    for i, x in enumerate(v):
        ax.text(i, x + 0.02, f"{x:.2f}", ha="center", fontsize=8)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    a = json.loads((MODELS_DIR / "anomaly_detection" / "metrics.json").read_text())
    f = json.loads((MODELS_DIR / "failure_prediction" / "metrics.json").read_text())
    a3 = json.loads((MODELS_DIR / "anomaly_detection" / "approach3_metrics.json").read_text())
    t = a["test"]; c = t["cycle_level"]
    fig, ax = plt.subplots(1, 3, figsize=(15, 4.2))
    cm(ax[0], t["state_confusion_matrix_seed2001"]["matrix"], t["state_confusion_matrix_seed2001"]["labels"], "Approach 2 state classifier (test seed 2001)")
    bars(ax[1], c["recall_by_scenario"], "Abnormal-cycle recall by scenario (test)", "#3b82f6")
    bars(ax[2], c["recall_by_severity"], "Abnormal-cycle recall by severity (test)", "#f59e0b")
    fig.suptitle("Anomaly detection - SYNTHETIC data, test seeds 2001/2002", fontsize=11); fig.tight_layout(); fig.savefig(OUT / "anomaly_detection_test.png", dpi=130); plt.close(fig)

    fig, ax = plt.subplots(1, 2, figsize=(11, 4))
    A2 = a3["test"]["approach2_rules"]; k3 = [k for k in a3["test"] if k.startswith("approach3")][0]; A3 = a3["test"][k3]
    x = np.arange(3); w = 0.35
    ax[0].bar(x - w / 2, [A2["precision"], A2["recall"], A2["false_positive_rate"]], w, label="Approach 2 (rules)", color="#3b82f6")
    ax[0].bar(x + w / 2, [A3["precision"], A3["recall"], A3["false_positive_rate"]], w, label="Approach 3 (learned)", color="#ef4444")
    ax[0].set_xticks(x); ax[0].set_xticklabels(["precision", "recall", "false-positive rate"]); ax[0].legend(); ax[0].set_ylim(0, 1.1); ax[0].set_title("Test, abnormal cycles", fontsize=10)
    sc = list(A2["recall_by_scenario"]); ax[1].bar(np.arange(len(sc)) - w / 2, [A2["recall_by_scenario"][s][0] for s in sc], w, color="#3b82f6", label="Approach 2")
    ax[1].bar(np.arange(len(sc)) + w / 2, [A3["recall_by_scenario"][s][0] for s in sc], w, color="#ef4444", label="Approach 3")
    ax[1].set_xticks(range(len(sc))); ax[1].set_xticklabels([s.replace("_", "\n") for s in sc], fontsize=8); ax[1].set_ylim(0, 1.1); ax[1].set_title("Recall by scenario (INTERMITTENT held out of training)", fontsize=10); ax[1].legend()
    fig.suptitle("Approach 2 vs Approach 3 - SYNTHETIC data", fontsize=11); fig.tight_layout(); fig.savefig(OUT / "approach2_vs_approach3.png", dpi=130); plt.close(fig)

    ft = f["test"]
    fig, ax = plt.subplots(1, 3, figsize=(16, 4.4))
    cm(ax[0], ft["confusion_matrix"]["matrix"], ft["confusion_matrix"]["labels"], "Failure model confusion (test)")
    bars(ax[1], {k: v["class_recall"] for k, v in ft["by_scenario"].items()}, "Class recall by scenario", "#10b981")
    bars(ax[2], {k: v["class_recall"] for k, v in ft["by_severity"].items()}, "Class recall by degradation severity", "#f59e0b")
    fig.suptitle("Failure-risk model - SYNTHETIC data, test seeds 2001/2002", fontsize=11); fig.tight_layout(); fig.savefig(OUT / "failure_model_test.png", dpi=130); plt.close(fig)

    v = a["validation"]; names = list(v)
    fig, ax = plt.subplots(figsize=(7, 3.6))
    ax.bar(names, [v[n]["abnormal_f1"] for n in names], color="#6366f1"); ax.set_ylim(0, 1.05); ax.set_title("State-classifier candidates: abnormal-cycle F1 on VALIDATION", fontsize=10)
    for i, n in enumerate(names): ax.text(i, v[n]["abnormal_f1"] + 0.015, f"{v[n]['abnormal_f1']:.3f}", ha="center", fontsize=8)
    fig.tight_layout(); fig.savefig(OUT / "state_classifier_candidates_validation.png", dpi=130); plt.close(fig)
    print("wrote", sorted(p.name for p in OUT.iterdir()))


if __name__ == "__main__":
    main()
