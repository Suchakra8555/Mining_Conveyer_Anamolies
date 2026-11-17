from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from app.database.models import Anomaly, FailurePrediction, SensorReading, SensorStation, VisionDetection
from app.simulator.engine import from_epoch
from .deps import get_db, get_pipeline

router = APIRouter(prefix="/api", tags=["system"])


@router.get("/health")
def health(p=Depends(get_pipeline)):
    return {"status": "ok", "anomaly_model_loaded": p.anom_model is not None, "failure_model_loaded": p.fail_model is not None,
            "vision_detector": p.detector.kind, "vision_detector_validated": p.detector.validated,
            "simulation_running": p.sim.running}


@router.get("/dashboard/summary")
def summary(db: Session = Depends(get_db), p=Depends(get_pipeline)):
    sts = db.execute(select(SensorStation)).scalars().all()
    counts = {k: sum(1 for s in sts if s.status == k) for k in ("NORMAL", "ABNORMAL", "PREDICTED_FAILURE", "OFFLINE", "UNKNOWN")}
    active = db.execute(select(Anomaly).where(Anomaly.status == "ACTIVE")).scalars().all()
    now = from_epoch(p.sim.now)
    latest = db.execute(select(FailurePrediction).where(FailurePrediction.predicted_at >= now - timedelta(hours=3), FailurePrediction.risk_score >= 0.5)).scalars().all()
    # station-level newest prediction only
    best = {}
    for f in latest:
        if f.station_id not in best or f.predicted_at > best[f.station_id].predicted_at:
            best[f.station_id] = f
    crit = [a for a in active if a.severity == "HIGH"]
    crit_pred = [f for f in best.values() if f.severity in ("CRITICAL", "HIGH")]
    rpms = []
    for s in sts:
        r = db.execute(select(SensorReading.motor_rpm).where(SensorReading.station_id == s.id, SensorReading.motor_rpm.is_not(None)).order_by(desc(SensorReading.timestamp)).limit(1)).scalar()
        if r is not None:
            rpms.append(r)
    avg = sum(rpms) / len(rpms) if rpms else 0.0
    op = "RUNNING" if avg > 10 else "IDLE" if avg > 0.2 else "STOPPED"
    vis = db.execute(select(func.count()).select_from(VisionDetection).where(VisionDetection.is_repeat == False)).scalar()  # noqa: E712
    return {"conveyor_status": op, "conveyor_length_m": p.sim.cfg.length_m, "total_stations": len(sts),
            "healthy_stations": counts["NORMAL"], "abnormal_stations": counts["ABNORMAL"],
            "predicted_failure_stations": counts["PREDICTED_FAILURE"], "offline_stations": counts["OFFLINE"],
            "unknown_stations": counts["UNKNOWN"], "active_anomalies": len(active),
            "critical_alerts": len(crit) + len(crit_pred), "vision_incidents": vis,
            "simulated_time": now.isoformat(), "simulation_running": p.sim.running}
