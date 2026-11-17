"""Persist vision detections with belt-segment association and duplicate (repeat-observation) handling."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

import cv2
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import DATA_DIR
from app.database.models import BeltSegment, VisionDetection
from app.vision.detector import annotate, load_image, same_defect

SEVERITY_WEIGHT = {"TEAR": 0.5, "HOLE": 0.4, "CRACK": 0.25, "EDGE_DAMAGE": 0.25, "ABRASION": 0.15}
# same class + same segment + overlapping/containing image region => same physical defect (see vision.detector.same_defect)
ANNOTATED_DIR = DATA_DIR / "vision" / "annotated"


def rel(p: Path) -> str:
    try:
        return str(Path(p).resolve().relative_to(DATA_DIR.resolve()))
    except ValueError:
        return str(p)


def analyze_and_store(db: Session, detector, image_path: Path, segment_id: str | None, belt_position: float | None,
                      now: datetime, location_source: str = "SIMULATED", save_annotated: bool = True) -> list[dict]:
    img = load_image(image_path)
    dets = detector.detect(img)
    ann_rel = None
    if dets and save_annotated:
        ANNOTATED_DIR.mkdir(parents=True, exist_ok=True)
        ap = ANNOTATED_DIR / f"{Path(image_path).stem}_ann.jpg"
        cv2.imwrite(str(ap), annotate(img, dets))
        ann_rel = rel(ap)
    seg = db.get(BeltSegment, segment_id) if segment_id else None
    out = []
    for d in dets:
        prior = None
        if segment_id:
            cands = db.execute(select(VisionDetection).where(VisionDetection.belt_segment_id == segment_id,
                               VisionDetection.damage_type == d.damage_type, VisionDetection.is_repeat == False)).scalars().all()  # noqa: E712
            for c in cands:
                if c.bounding_box and same_defect(c.bounding_box, d.bbox):
                    prior = c; break
        row = VisionDetection(image_path=rel(image_path), annotated_path=ann_rel, damage_type=d.damage_type,
                              confidence=d.confidence, bounding_box=list(d.bbox), belt_segment_id=segment_id,
                              belt_position=belt_position, location_source=location_source if segment_id else "UNKNOWN",
                              detector_kind=detector.kind, bbox_area=d.area, detected_at=now)
        if prior is None:
            db.add(row); db.flush()
            row.incident_id = row.id; row.first_area = row.latest_area = d.area
            if seg is not None:
                seg.segment_health = max(0.0, seg.segment_health - SEVERITY_WEIGHT.get(d.damage_type, 0.2))
        else:
            row.is_repeat = True; row.incident_id = prior.id
            db.add(row)
            prior.observation_count += 1; prior.latest_area = d.area; prior.confidence = max(prior.confidence, d.confidence)
        out.append({"damage_type": d.damage_type, "confidence": d.confidence, "bbox": list(d.bbox),
                    "is_repeat": prior is not None, "incident_id": row.incident_id, "segment_id": segment_id})
    return out
