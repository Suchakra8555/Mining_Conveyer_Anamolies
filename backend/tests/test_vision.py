import json
from pathlib import Path

import cv2
import numpy as np
import pytest

from app.core.config import DATA_DIR
from app.vision.detector import HeuristicDemoDetector, annotate, iou, load_detector, load_image, preprocess
from app.vision.synth import make_image
from app.vision.tracker import BeltTracker

SAMPLES = DATA_DIR / "vision" / "samples"


def test_image_loading_and_preprocessing(tmp_path):
    arr, _ = make_image("TEAR", 1, 1)
    p = tmp_path / "a.jpg"; cv2.imwrite(str(p), arr)
    img = load_image(p)
    assert img.ndim == 3
    big = np.zeros((2000, 3000, 3), np.uint8)
    assert max(preprocess(big).shape[:2]) == 640
    with pytest.raises(ValueError):
        load_image(b"not an image")


def test_loader_falls_back_to_heuristic_without_weights(tmp_path):
    d = load_detector(tmp_path / "missing.pt")
    assert d.kind == "HEURISTIC_DEMO" and d.validated is False


@pytest.mark.parametrize("kind", ["CRACK", "TEAR", "HOLE", "ABRASION", "EDGE_DAMAGE"])
def test_cpu_inference_detects_synthetic_defects(kind):
    arr, ann = make_image(kind, 1, 321)
    dets = HeuristicDemoDetector().detect(cv2.cvtColor(arr, cv2.COLOR_RGB2BGR))
    assert any(d.damage_type == kind and iou(d.bbox, ann[0]["bbox"]) > 0.3 for d in dets)


def test_normal_image_has_no_detections():
    arr, _ = make_image(None, 0, 5)
    assert HeuristicDemoDetector().detect(cv2.cvtColor(arr, cv2.COLOR_RGB2BGR)) == []


def test_detection_schema_and_annotation():
    arr, _ = make_image("HOLE", 1, 3)
    bgr = cv2.cvtColor(arr, cv2.COLOR_RGB2BGR)
    dets = HeuristicDemoDetector().detect(bgr)
    d = dets[0]
    assert 0 <= d.confidence <= 1 and len(d.bbox) == 4
    assert annotate(bgr, dets).shape == preprocess(bgr).shape


def test_tracker_modulo_position():
    t = BeltTracker(5000, 50, camera_pos_m=0)
    t.advance(5000)                                     # exactly one loop
    assert t.under_camera() == 0 and t.position_of(10) == pytest.approx(500)
    t.advance(1250)
    assert t.position_of(0) == pytest.approx(1250)


def test_tracker_same_segment_returns_after_one_loop_and_counts_passes():
    t = BeltTracker(5000, 50)
    first = t.advance(60.0)
    seen = list(first)
    for _ in range(100):                                # 5000 m more in steps
        seen += t.advance(50.0)
    assert seen.count(first[0]) == 2 and t.passes[first[0]] == 2


def test_tracker_does_not_skip_segments_on_large_steps():
    t = BeltTracker(5000, 50)
    crossed = t.advance(240.0)                          # 4.8 segments in one tick
    assert len(crossed) in (4, 5) and len(set(crossed)) == len(crossed)
