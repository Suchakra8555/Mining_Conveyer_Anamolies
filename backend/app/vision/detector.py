"""Vision inference interface. CPU only.

Two implementations:
 * UltralyticsDetector - loads a conveyor-defect YOLO `.pt` if (a) `ultralytics` is installed and (b) the weights file exists.
   No such weights could be obtained in the build environment, so this path is implemented but UNTESTED against real weights.
 * HeuristicDemoDetector - classical OpenCV contrast heuristics. NOT a trained/validated model; labelled as a DEMO everywhere.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

SUPPORTED_CLASSES = ["CRACK", "TEAR", "HOLE", "ABRASION", "EDGE_DAMAGE"]


@dataclass
class Detection:
    damage_type: str
    confidence: float
    bbox: tuple[int, int, int, int]      # x1, y1, x2, y2 in pixels

    @property
    def area(self) -> int:
        return max(0, self.bbox[2] - self.bbox[0]) * max(0, self.bbox[3] - self.bbox[1])


def load_image(path_or_bytes) -> np.ndarray:
    if isinstance(path_or_bytes, (bytes, bytearray)):
        arr = cv2.imdecode(np.frombuffer(path_or_bytes, np.uint8), cv2.IMREAD_COLOR)
    else:
        arr = cv2.imread(str(path_or_bytes), cv2.IMREAD_COLOR)
    if arr is None:
        raise ValueError("cannot decode image")
    return arr


def preprocess(img: np.ndarray, max_side: int = 640) -> np.ndarray:
    h, w = img.shape[:2]
    s = max_side / max(h, w)
    return cv2.resize(img, (int(w * s), int(h * s))) if s < 1 else img


def iou(a, b) -> float:
    ix = max(0, min(a[2], b[2]) - max(a[0], b[0])); iy = max(0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    u = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / u if u > 0 else 0.0


def same_defect(a, b, iou_min: float = 0.3, contain_min: float = 0.7) -> bool:
    """Same physical defect if boxes overlap (IoU) or one contains the other (a defect that GREW still contains its old extent)."""
    ix = max(0, min(a[2], b[2]) - max(a[0], b[0])); iy = max(0, min(a[3], b[3]) - max(a[1], b[1]))
    smaller = min((a[2] - a[0]) * (a[3] - a[1]), (b[2] - b[0]) * (b[3] - b[1]))
    return iou(a, b) >= iou_min or (smaller > 0 and ix * iy / smaller >= contain_min)


class HeuristicDemoDetector:
    kind = "HEURISTIC_DEMO"
    validated = False
    confidence_meaning = "heuristic contrast score in [0,1]; not a probability"

    def detect(self, img: np.ndarray) -> list[Detection]:
        img = preprocess(img)
        g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        h, w = g.shape
        small = cv2.resize(g, (w // 4, h // 4), interpolation=cv2.INTER_AREA)   # background at 1/4 res: robust to large patches
        bg = cv2.resize(cv2.medianBlur(small, 51), (w, h), interpolation=cv2.INTER_LINEAR)
        diff = g.astype(np.int16) - bg.astype(np.int16)
        out: list[Detection] = []
        # dark defects: crack / tear / hole / edge damage
        dark = (diff < -30).astype(np.uint8)
        dark = cv2.morphologyEx(dark, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5)))
        n, lab, stats, _ = cv2.connectedComponentsWithStats(dark, 8)
        for i in range(1, n):
            x, y, bw, bh, area = stats[i]
            if area < 60:
                continue
            m = (lab[y:y + bh, x:x + bw] == i).astype(np.uint8)
            cnts, _ = cv2.findContours(m, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            (rw, rh) = cv2.minAreaRect(max(cnts, key=cv2.contourArea))[1]
            major, minor = max(rw, rh), max(min(rw, rh), 1.0)
            fill = area / float(bw * bh)
            depth = float(-diff[y:y + bh, x:x + bw][m > 0].mean())
            touches_edge = y <= 14 or (y + bh) >= h - 14
            if touches_edge and bw >= 30:
                cls = "EDGE_DAMAGE"
            elif area / max(major, 1.0) <= 7 and major >= 40:    # thin: mean thickness (area/length) <= 7 px
                cls = "CRACK"
            elif major / minor >= 3 and area / max(major, 1.0) > 7:
                cls = "TEAR"
            elif major / minor < 2.2 and area >= 250:
                cls = "HOLE"
            else:
                continue
            out.append(Detection(cls, float(min(1.0, depth / 70.0)), (int(x), int(y), int(x + bw), int(y + bh))))
        # bright, textured worn patches: abrasion
        br = (diff > 25).astype(np.uint8)
        br[:14, :] = 0; br[-14:, :] = 0
        br = cv2.morphologyEx(br, cv2.MORPH_OPEN, np.ones((5, 5), np.uint8))
        br = cv2.morphologyEx(br, cv2.MORPH_CLOSE, np.ones((15, 15), np.uint8))
        n, lab, stats, _ = cv2.connectedComponentsWithStats(br, 8)
        for i in range(1, n):
            x, y, bw, bh, area = stats[i]
            if area >= 1500:
                out.append(Detection("ABRASION", float(min(1.0, diff[y:y + bh, x:x + bw].mean() / 60.0)), (int(x), int(y), int(x + bw), int(y + bh))))
        return out


class UltralyticsDetector:
    kind = "YOLO_PRETRAINED"
    validated = False   # only a real held-out evaluation could set this True
    confidence_meaning = "model confidence (uncalibrated)"

    def __init__(self, weights: Path):
        from ultralytics import YOLO  # lazy: ultralytics/torch are optional
        self.model = YOLO(str(weights))
        self.names = self.model.names

    def detect(self, img):
        res = self.model.predict(preprocess(img), device="cpu", verbose=False)[0]
        out = []
        for b in res.boxes:
            name = str(self.names[int(b.cls)]).upper()
            if name in SUPPORTED_CLASSES:       # report supported defect classes only
                x1, y1, x2, y2 = map(int, b.xyxy[0].tolist())
                out.append(Detection(name, float(b.conf), (x1, y1, x2, y2)))
        return out


def load_detector(weights: Path | None):
    if weights and Path(weights).exists():
        try:
            return UltralyticsDetector(Path(weights))
        except Exception:  # ultralytics missing or weights incompatible -> honest fallback
            pass
    return HeuristicDemoDetector()


def annotate(img: np.ndarray, dets: list[Detection]) -> np.ndarray:
    img = preprocess(img).copy()
    for d in dets:
        x1, y1, x2, y2 = d.bbox
        cv2.rectangle(img, (x1, y1), (x2, y2), (0, 0, 255), 2)
        cv2.putText(img, f"{d.damage_type} {d.confidence:.2f}", (x1, max(14, y1 - 5)), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 255), 1)
    return img
