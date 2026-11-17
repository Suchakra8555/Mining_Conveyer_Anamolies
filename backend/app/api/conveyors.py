from __future__ import annotations

from datetime import timedelta

import numpy as np
from fastapi import APIRouter, Depends, Query
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.database.models import Anomaly, Conveyor, FailurePrediction, SensorReading, SensorStation
from app.schemas import ConveyorOut, StationOut
from app.simulator.engine import CHANNELS, EXTENDED_CHANNELS, PAPER_CHANNELS, from_epoch
from .deps import conveyor_or_404, get_db, get_pipeline, station_or_404

router = APIRouter(prefix="/api", tags=["conveyors & sensors"])


def _station(s: SensorStation) -> dict:
    return {**StationOut.model_validate(s).model_dump(), "position_km": s.position_meters / 1000.0}


@router.get("/conveyors", response_model=list[ConveyorOut])
def conveyors(db: Session = Depends(get_db)):
    return db.execute(select(Conveyor)).scalars().all()


@router.get("/conveyors/{cid}", response_model=ConveyorOut)
def conveyor(cid: str, db: Session = Depends(get_db)):
    return conveyor_or_404(db, cid)


@router.get("/conveyors/{cid}/stations")
def stations(cid: str, db: Session = Depends(get_db)):
    c = conveyor_or_404(db, cid)
    rows = db.execute(select(SensorStation).where(SensorStation.conveyor_id == c.id).order_by(SensorStation.position_meters)).scalars().all()
    out = []
    for s in rows:
        d = _station(s)
        d["latest"] = _latest(db, s)
        d["evidence"] = (s.status_evidence or {}).get("evidence", [])
        out.append(d)
    return out


def _latest(db, s):
    r = db.execute(select(SensorReading).where(SensorReading.station_id == s.id).order_by(desc(SensorReading.timestamp)).limit(1)).scalars().first()
    if not r:
        return None
    return {"timestamp": r.timestamp.isoformat(), **{c: getattr(r, c) for c in CHANNELS}, "data_quality_status": r.data_quality_status}


@router.get("/sensors")
def sensors(db: Session = Depends(get_db)):
    """Sensor suite per station: channels (research-aligned vs extended) and reliability."""
    out = []
    for s in db.execute(select(SensorStation).order_by(SensorStation.position_meters)).scalars():
        out.append({"station_id": s.id, "station_name": s.station_name, "sensor_health": s.sensor_health,
                    "channels": [{"name": c, "origin": "RESEARCH_PAPER" if c in PAPER_CHANNELS else "EXTENDED_SIMULATED"} for c in CHANNELS]
                    + [{"name": "differential_pressure", "origin": "RESEARCH_PAPER (derived)"}]})
    return out


@router.get("/sensors/{station}/readings")
def readings(station: str, hours: float = Query(6, gt=0, le=72), max_points: int = Query(300, ge=10, le=2000),
             db: Session = Depends(get_db), p=Depends(get_pipeline)):
    """Time series for a station over the last `hours` of SIMULATED time, bucket-averaged to <= max_points."""
    s = station_or_404(db, station)
    now = from_epoch(p.sim.now)
    rows = db.execute(select(SensorReading).where(SensorReading.station_id == s.id, SensorReading.timestamp >= now - timedelta(hours=hours))
                      .order_by(SensorReading.timestamp)).scalars().all()
    k = max(1, int(np.ceil(len(rows) / max_points)))
    out = []
    for i in range(0, len(rows), k):
        chunk = rows[i:i + k]
        d = {"timestamp": chunk[len(chunk) // 2].timestamp.isoformat() + "Z" if chunk[0].timestamp.tzinfo is None else chunk[len(chunk) // 2].timestamp.isoformat()}
        for c in CHANNELS:
            v = [getattr(x, c) for x in chunk if getattr(x, c) is not None and x.data_quality_status in ("OK", "STUCK")]
            d[c] = float(np.mean(v)) if v else None
        bad = [x.data_quality_status for x in chunk if x.data_quality_status != "OK"]
        d["data_quality_status"] = bad[0] if bad else "OK"
        out.append(d)
    return {"station": s.station_name, "bucket": k, "points": out}


@router.get("/stations/{station}/health")
def station_health(station: str, db: Session = Depends(get_db), p=Depends(get_pipeline)):
    s = station_or_404(db, station)
    now = from_epoch(p.sim.now)
    anoms = db.execute(select(Anomaly).where(Anomaly.station_id == s.id, Anomaly.status == "ACTIVE")).scalars().all()
    pred = db.execute(select(FailurePrediction).where(FailurePrediction.station_id == s.id).order_by(desc(FailurePrediction.predicted_at)).limit(1)).scalars().first()
    recent = db.execute(select(SensorReading.data_quality_status).where(SensorReading.station_id == s.id).order_by(desc(SensorReading.timestamp)).limit(30)).scalars().all()
    dq = {k: recent.count(k) for k in set(recent)}
    return {**_station(s), "evidence": (s.status_evidence or {}).get("evidence", []), "latest": _latest(db, s),
            "data_quality_last_30": dq,
            "active_anomalies": [{"id": a.id, "type": a.anomaly_type, "severity": a.severity, "description": a.description, "detected_at": a.detected_at.isoformat()} for a in anoms],
            "latest_prediction": None if pred is None else {"component": pred.component, "failure_type": pred.failure_type, "risk_score": pred.risk_score,
                                                           "severity": pred.severity, "estimated_time_to_failure_hours": pred.estimated_time_to_failure,
                                                           "predicted_at": pred.predicted_at.isoformat()},
            "simulated_time": now.isoformat()}
