"""SYNTHETIC belt-surface images with known defect annotations.

Why: public conveyor-defect datasets/weights could not be downloaded in the build sandbox (Hugging Face, Roboflow,
Kaggle, Zenodo blocked). These images are procedurally generated stand-ins so the pipeline can be exercised end-to-end.
They are NOT real belt photographs and must never be used to claim real-world detection accuracy.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter

W, H = 640, 320
CLASSES = ["CRACK", "TEAR", "HOLE", "ABRASION", "EDGE_DAMAGE"]


def _base(rng) -> np.ndarray:
    img = rng.normal(70, 6, (H, W))
    img += np.sin(np.linspace(0, 40, W))[None, :] * 2.5                 # faint fabric ribs
    img += rng.normal(0, 3, (H, 1))
    big = np.array(Image.fromarray(np.clip(rng.normal(70, 12, (8, 16)), 0, 255).astype(np.uint8)).resize((W, H), Image.BICUBIC), float)
    img = 0.7 * img + 0.3 * big
    img[:10, :] += 60; img[-10:, :] += 60                                  # steel edge frame
    return img


def _line(img, pts, width, val):
    from PIL import ImageDraw
    pil = Image.fromarray(np.clip(img, 0, 255).astype(np.uint8))
    ImageDraw.Draw(pil).line(pts, fill=int(val), width=int(width))
    return np.array(pil, float)


def make_image(kind: str | None, stage: int, seed: int):
    """kind None -> normal. stage 0..2 scales defect size (wear progression). Returns (uint8 RGB array, annotations)."""
    rng = np.random.default_rng(seed)
    img = _base(rng)
    ann = []
    s = (0.6, 1.0, 1.45)[stage]
    cx, cy = int(rng.integers(180, W - 180)), int(rng.integers(90, H - 90))
    if kind == "CRACK":
        L = int(110 * s); pts = [(cx - L // 2, cy)]
        for k in range(1, 9):
            pts.append((pts[-1][0] + L // 8, cy + int(rng.integers(-10, 10))))
        img = _line(img, pts, 3, 20)
        xs, ys = [p[0] for p in pts], [p[1] for p in pts]
        ann = [(min(xs) - 3, min(ys) - 3, max(xs) + 3, max(ys) + 3)]
    elif kind == "TEAR":
        L = int(190 * s); wd = int(16 * s)
        pts = [(cx - L // 2, cy), (cx - L // 6, cy + 8), (cx + L // 6, cy - 6), (cx + L // 2, cy + 3)]
        img = _line(img, pts, wd, 12)
        ann = [(cx - L // 2 - wd // 2, cy - wd - 8, cx + L // 2 + wd // 2, cy + wd + 8)]
    elif kind == "HOLE":
        r = int(18 * s)
        yy, xx = np.mgrid[0:H, 0:W]
        m = ((xx - cx) / (r * 1.2)) ** 2 + ((yy - cy) / r) ** 2 < 1
        img[m] = 10
        ann = [(cx - int(r * 1.2), cy - r, cx + int(r * 1.2), cy + r)]
    elif kind == "ABRASION":
        w, h = int(120 * s), int(60 * s)
        x0, y0 = cx - w // 2, cy - h // 2
        patch = img[y0:y0 + h, x0:x0 + w]
        img[y0:y0 + h, x0:x0 + w] = patch * 0.4 + 118 + rng.normal(0, 4, patch.shape)
        ann = [(x0, y0, x0 + w, y0 + h)]
    elif kind == "EDGE_DAMAGE":
        w, h = int(90 * s), int(28 * s)
        x0 = cx - w // 2
        top = bool(rng.integers(0, 2))
        ys = slice(0, h) if top else slice(H - h, H)
        img[ys, x0:x0 + w] = 12
        ann = [(x0, 0 if top else H - h, x0 + w, h if top else H)]
    pil = Image.fromarray(np.clip(img, 0, 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(0.6)).convert("RGB")
    return np.array(pil), [{"class": kind, "bbox": list(map(int, a))} for a in ann]


def generate_sample_set(out_dir: Path, n_defect_segments: int = 8, n_normal: int = 6, seed: int = 42) -> dict:
    """8 'damaged belt segments' x 3 wear stages + normal images. Writes JPEGs + annotations.json."""
    out_dir.mkdir(parents=True, exist_ok=True)
    meta = {"synthetic": True, "images": {}, "damaged_segments": []}
    for i in range(n_normal):
        arr, ann = make_image(None, 0, seed * 100 + i)
        name = f"normal_{i:02d}.jpg"
        Image.fromarray(arr).save(out_dir / name, quality=88)
        meta["images"][name] = {"annotations": ann, "kind": None, "stage": 0}
    for d in range(n_defect_segments):
        kind = CLASSES[d % len(CLASSES)]
        files = []
        for stage in range(3):
            arr, ann = make_image(kind, stage, seed * 1000 + d * 10)       # same seed -> same location, growing size
            name = f"defect_{d:02d}_{kind.lower()}_s{stage}.jpg"
            Image.fromarray(arr).save(out_dir / name, quality=88)
            meta["images"][name] = {"annotations": ann, "kind": kind, "stage": stage}
            files.append(name)
        meta["damaged_segments"].append({"kind": kind, "files": files})
    (out_dir / "annotations.json").write_text(json.dumps(meta, indent=1))
    return meta
