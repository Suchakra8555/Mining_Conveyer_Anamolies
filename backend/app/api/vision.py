from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from app.core.config import DATA_DIR
from app.database.models import BeltSegment, VisionDetection
from app.schemas import Page, VisionOut
from app.services import vision_service
from app.simulator.engine import from_epoch
from .deps import get_db, get_pipeline

router = APIRouter(prefix="/api/vision", tags=["vision"])
UPLOADS = DATA_DIR / "vision" / "uploads"


def _o(v: VisionDetection) -> VisionOut:
    o = VisionOut.model_validate(v)
    if v.first_area and not v.is_repeat:
        o.growth_ratio = round(v.latest_area / v.first_area, 2)
    return o


@router.get("/detections", response_model=Page[VisionOut])
def detections(incidents_only: bool = True, damage_type: str | None = None, segment: str | None = None,
               limit: int = Query(50, ge=1, le=500), offset: int = Query(0, ge=0), db: Session = Depends(get_db)):
    """incidents_only=true returns one row per physical defect (repeat observations folded into observation_count)."""
    q = select(VisionDetection)
    if incidents_only: q = q.where(VisionDetection.is_repeat == False)  # noqa: E712
    if damage_type: q = q.where(VisionDetection.damage_type == damage_type.upper())
    if segment: q = q.where(VisionDetection.belt_segment_id == segment.upper())
    total = db.execute(select(func.count()).select_from(q.subquery())).scalar()
    rows = db.execute(q.order_by(desc(VisionDetection.detected_at)).limit(limit).offset(offset)).scalars().all()
    return Page(items=[_o(r) for r in rows], total=total, limit=limit, offset=offset)


@router.get("/incidents/{iid}/history", response_model=list[VisionOut])
def history(iid: str, db: Session = Depends(get_db)):
    rows = db.execute(select(VisionDetection).where(VisionDetection.incident_id == iid).order_by(VisionDetection.detected_at)).scalars().all()
    return [_o(r) for r in rows]


@router.get("/segments")
def segments(damaged_only: bool = True, limit: int = Query(120, ge=1, le=500), db: Session = Depends(get_db), p=Depends(get_pipeline)):
    q = select(BeltSegment)
    if damaged_only: q = q.where(BeltSegment.segment_health < 1.0)
    rows = db.execute(q.order_by(BeltSegment.segment_health).limit(limit)).scalars().all()
    return {"tracker": p.tracker.state(), "segments": [{"id": s.id, "position_meters": round(p.tracker.position_of(int(s.id[3:])), 1), "segment_health": round(s.segment_health, 2),
                                                        "pass_count": s.pass_count, "last_observed_at": s.last_observed_at.isoformat() if s.last_observed_at else None} for s in rows]}


@router.get("/info")
def info(p=Depends(get_pipeline)):
    d = p.detector
    ev = DATA_DIR.parent / "models" / "vision" / "demo_eval.json"
    return {"detector_kind": d.kind, "validated": d.validated, "confidence_meaning": d.confidence_meaning,
            "supported_classes": ["CRACK", "TEAR", "HOLE", "ABRASION", "EDGE_DAMAGE"],
            "images": "SYNTHETIC procedurally generated belt images (no public dataset could be downloaded in the build environment)",
            "location": "belt segment / position are SIMULATED metadata, not derived from the image",
            "demo_eval_on_synthetic": json.loads(ev.read_text()) if ev.exists() else None}


@router.get("/samples")
def samples():
    d = DATA_DIR / "vision" / "samples"
    meta = json.loads((d / "annotations.json").read_text())
    return [{"name": k, "kind": v["kind"], "stage": v["stage"]} for k, v in meta["images"].items()]


@router.post("/analyze")
async def analyze(file: UploadFile | None = File(None), sample: str | None = Form(None), segment_id: str | None = Form(None),
                  db: Session = Depends(get_db), p=Depends(get_pipeline)):
    """Analyse an uploaded image or a bundled sample. If no segment_id is given, the segment currently under the simulated
    camera is used (location_source=SIMULATED); a user-supplied segment_id is recorded as USER_SUPPLIED."""
    if file is None and sample is None:
        raise HTTPException(422, "provide an image file or a sample name")
    if file is not None:
        data = await file.read()
        if len(data) > 10_000_000:
            raise HTTPException(413, "image too large")
        UPLOADS.mkdir(parents=True, exist_ok=True)
        name = Path(file.filename or "upload.jpg").name
        path = UPLOADS / f"{int(datetime.now().timestamp())}_{name}"
        path.write_bytes(data)
    else:
        path = DATA_DIR / "vision" / "samples" / Path(sample).name
        if not path.exists():
            raise HTTPException(404, "sample not found")
    from app.vision.detector import load_image
    try:
        load_image(path)
    except ValueError:
        raise HTTPException(422, "file is not a decodable image")
    with p.lock:
        src = "USER_SUPPLIED" if segment_id else "SIMULATED"
        seg = segment_id.upper() if segment_id else p.tracker.segment_id(p.tracker.under_camera())
        if db.get(BeltSegment, seg) is None:
            raise HTTPException(404, f"unknown belt segment {seg}")
        pos = p.tracker.position_of(int(seg[3:]))
        res = vision_service.analyze_and_store(db, p.detector, path, seg, pos, from_epoch(p.sim.now), src)
        db.commit()
    return {"image": vision_service.rel(path), "segment_id": seg, "location_source": src, "detector_kind": p.detector.kind,
            "validated": p.detector.validated, "detections": res}


@router.get("/files/{path:path}")
def files(path: str):
    full = (DATA_DIR / path).resolve()
    if DATA_DIR.resolve() not in full.parents or not full.is_file() or full.suffix.lower() not in (".jpg", ".jpeg", ".png"):
        raise HTTPException(404)
    return FileResponse(full)
