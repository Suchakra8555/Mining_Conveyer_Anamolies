from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from app.database.models import Anomaly, FailurePrediction, SensorStation
from app.schemas import AnomalyOut, Page, PredictionOut
from app.simulator.engine import from_epoch
from .deps import get_db, get_pipeline, station_or_404

router = APIRouter(prefix="/api", tags=["anomalies & predictions"])


def _a(a: Anomaly, st: SensorStation) -> AnomalyOut:
    o = AnomalyOut.model_validate(a)
    o.station_name, o.position_meters = st.station_name, st.position_meters
    return o


def _p(f: FailurePrediction, st: SensorStation) -> PredictionOut:
    o = PredictionOut.model_validate({**{c: getattr(f, c) for c in ("id", "station_id", "component", "failure_type", "risk_score", "severity",
                                      "prediction_basis", "class_scores", "predicted_at")}, "estimated_time_to_failure_hours": f.estimated_time_to_failure})
    o.station_name, o.position_meters = st.station_name, st.position_meters
    return o


@router.get("/anomalies", response_model=Page[AnomalyOut])
def anomalies(status: str | None = None, severity: str | None = None, station: str | None = None, anomaly_type: str | None = None,
              limit: int = Query(50, ge=1, le=500), offset: int = Query(0, ge=0), db: Session = Depends(get_db)):
    q = select(Anomaly, SensorStation).join(SensorStation, SensorStation.id == Anomaly.station_id)
    if status: q = q.where(Anomaly.status == status.upper())
    if severity: q = q.where(Anomaly.severity == severity.upper())
    if anomaly_type: q = q.where(Anomaly.anomaly_type == anomaly_type.upper())
    if station: q = q.where(SensorStation.id == station_or_404(db, station).id)
    total = db.execute(select(func.count()).select_from(q.subquery())).scalar()
    rows = db.execute(q.order_by(desc(Anomaly.detected_at)).limit(limit).offset(offset)).all()
    return Page(items=[_a(a, s) for a, s in rows], total=total, limit=limit, offset=offset)


@router.get("/anomalies/{aid}", response_model=AnomalyOut)
def anomaly(aid: str, db: Session = Depends(get_db)):
    r = db.execute(select(Anomaly, SensorStation).join(SensorStation, SensorStation.id == Anomaly.station_id).where(Anomaly.id == aid)).first()
    if not r:
        raise HTTPException(404, "anomaly not found")
    return _a(*r)


@router.get("/predictions", response_model=Page[PredictionOut])
def predictions(station: str | None = None, component: str | None = None, min_risk: float = Query(0.5, ge=0, le=1),
                latest_only: bool = True, limit: int = Query(50, ge=1, le=500), offset: int = Query(0, ge=0),
                db: Session = Depends(get_db), p=Depends(get_pipeline)):
    """Default: the newest above-threshold prediction per station (recent 3 simulated hours)."""
    q = select(FailurePrediction, SensorStation).join(SensorStation, SensorStation.id == FailurePrediction.station_id).where(FailurePrediction.risk_score >= min_risk)
    if station: q = q.where(SensorStation.id == station_or_404(db, station).id)
    if component: q = q.where(FailurePrediction.component == component.upper())
    if latest_only:
        q = q.where(FailurePrediction.predicted_at >= from_epoch(p.sim.now) - timedelta(hours=3))
    rows = db.execute(q.order_by(desc(FailurePrediction.predicted_at))).all()
    if latest_only:
        seen, keep = set(), []
        for f, s in rows:
            if s.id not in seen:
                seen.add(s.id); keep.append((f, s))
        rows = keep
    total = len(rows)
    rows = rows[offset:offset + limit]
    return Page(items=[_p(f, s) for f, s in rows], total=total, limit=limit, offset=offset)


@router.get("/predictions/trend/{station}")
def trend(station: str, hours: float = Query(24, gt=0, le=72), db: Session = Depends(get_db), p=Depends(get_pipeline)):
    """Risk-score history for a station (degradation trend)."""
    s = station_or_404(db, station)
    rows = db.execute(select(FailurePrediction).where(FailurePrediction.station_id == s.id, FailurePrediction.predicted_at >= from_epoch(p.sim.now) - timedelta(hours=hours))
                      .order_by(FailurePrediction.predicted_at)).scalars().all()
    return {"station": s.station_name, "points": [{"t": r.predicted_at.isoformat(), "risk": r.risk_score, "component": r.component, "ttf_h": r.estimated_time_to_failure} for r in rows]}


@router.get("/predictions/{pid}", response_model=PredictionOut)
def prediction(pid: str, db: Session = Depends(get_db)):
    r = db.execute(select(FailurePrediction, SensorStation).join(SensorStation, SensorStation.id == FailurePrediction.station_id).where(FailurePrediction.id == pid)).first()
    if not r:
        raise HTTPException(404, "prediction not found")
    return _p(*r)
