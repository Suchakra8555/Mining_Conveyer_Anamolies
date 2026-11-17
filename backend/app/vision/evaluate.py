"""Evaluate the heuristic DEMO detector against the SYNTHETIC annotations (not a real-world accuracy claim)."""
import json
import sys
from pathlib import Path

from app.core.config import DATA_DIR, MODELS_DIR
from .detector import HeuristicDemoDetector, iou, load_image
from .synth import CLASSES, generate_sample_set


def main():
    d = DATA_DIR / "vision" / "samples"
    meta = generate_sample_set(d) if not (d / "annotations.json").exists() else json.loads((d / "annotations.json").read_text())
    det = HeuristicDemoDetector()
    tp = {c: 0 for c in CLASSES}; fp = {c: 0 for c in CLASSES}; fn = {c: 0 for c in CLASSES}; conf = {}
    normal_fp = 0; n_normal = 0
    for name, m in meta["images"].items():
        ds = det.detect(load_image(d / name))
        gts = m["annotations"]
        if not gts:
            n_normal += 1; normal_fp += int(len(ds) > 0)
        used = set()
        for g in gts:
            hit = None
            for k, p in enumerate(ds):
                if k not in used and iou(g["bbox"], p.bbox) >= 0.3:
                    hit = k; break
            if hit is None:
                fn[g["class"]] += 1; conf.setdefault(g["class"], {}).setdefault("MISSED", 0); conf[g["class"]]["MISSED"] += 1
            else:
                used.add(hit); p = ds[hit]
                conf.setdefault(g["class"], {}).setdefault(p.damage_type, 0); conf[g["class"]][p.damage_type] += 1
                if p.damage_type == g["class"]: tp[g["class"]] += 1
                else: fn[g["class"]] += 1; fp[p.damage_type] += 1
        for k, p in enumerate(ds):
            if k not in used: fp[p.damage_type] += 1
    res = {"disclaimer": "Heuristic DEMO detector on SYNTHETIC images; says nothing about real belt photographs.",
           "images": len(meta["images"]), "normal_images": n_normal, "normal_images_with_false_detections": normal_fp,
           "per_class": {c: {"tp": tp[c], "fp": fp[c], "fn": fn[c],
                             "precision": round(tp[c] / (tp[c] + fp[c]), 3) if tp[c] + fp[c] else None,
                             "recall": round(tp[c] / (tp[c] + fn[c]), 3) if tp[c] + fn[c] else None} for c in CLASSES},
           "confusion": conf}
    out = MODELS_DIR / "vision"; out.mkdir(parents=True, exist_ok=True)
    (out / "demo_eval.json").write_text(json.dumps(res, indent=1))
    print(json.dumps(res, indent=1))


if __name__ == "__main__":
    main()
