"""Unified conveyor health engine. Combines evidence; no single ML model decides station status.

Priority (highest first):
  1 OFFLINE            sensor suite unavailable (stale data or disconnected) - never shown as healthy
  2 PREDICTED_FAILURE  recent failure prediction with risk >= RISK_THRESHOLD
  3 ABNORMAL           >=1 active operational anomaly (research cycle anomaly or signal rule)
  4 UNKNOWN            not enough information (too few valid readings, degraded sensors only)
  5 NORMAL             none of the above
Vision detections add evidence only when the belt segment has a known location (they do not change station status
on their own because the camera location is simulated metadata)."""
from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.database.models import Anomaly, FailurePrediction, SensorReading, SensorStation
from app.ml.failure_prediction.model import RISK_THRESHOLD
from .quality import sensor_health

PRED_VALID_FOR = timedelta(hours=3)     # simulated time
MIN_VALID_READINGS = 5


def evaluate_station(db: Session, st: SensorStation, now: datetime, step_s: float) -> dict:
    recent = db.execute(select(SensorReading).where(SensorReading.station_id == st.id)
                        .order_by(desc(SensorReading.timestamp)).limit(30)).scalars().all()
    statuses = [r.data_quality_status for r in recent]
    age = (now - recent[0].timestamp.replace(tzinfo=now.tzinfo)).total_seconds() if recent else None
    sh = sensor_health(statuses, age, step_s)
    evidence: list[dict] = []
    valid = sum(1 for s in statuses if s == "OK")
    actives = db.execute(select(Anomaly).where(Anomaly.station_id == st.id, Anomaly.status == "ACTIVE")).scalars().all()
    pred = db.execute(select(FailurePrediction).where(FailurePrediction.station_id == st.id,
                      FailurePrediction.predicted_at >= now - PRED_VALID_FOR).order_by(desc(FailurePrediction.predicted_at)).limit(1)).scalars().first()
    status = "NORMAL"
    if sh == "OFFLINE" or not recent:
        status = "OFFLINE" if recent else "UNKNOWN"
        evidence.append({"rule": "SENSOR_AVAILABILITY", "detail": f"sensor health {sh}; latest quality statuses {statuses[:5]}"})
    elif pred is not None and pred.risk_score >= RISK_THRESHOLD:
        status = "PREDICTED_FAILURE"
        evidence.append({"rule": "FAILURE_PREDICTION", "detail": f"{pred.component} {pred.failure_type} risk={pred.risk_score:.2f} ({pred.severity})"
                         + (f", est. {pred.estimated_time_to_failure:.0f} h to failure" if pred.estimated_time_to_failure is not None else "")})
    elif actives:
        status = "ABNORMAL"
    elif valid < MIN_VALID_READINGS or sh == "DEGRADED":
        status = "UNKNOWN"
        evidence.append({"rule": "INSUFFICIENT_DATA", "detail": f"{valid} valid of last {len(statuses)} readings; sensor health {sh}"})
    for a in actives:
        evidence.append({"rule": "ACTIVE_ANOMALY", "detail": f"{a.anomaly_type} ({a.severity}) since {a.detected_at.isoformat()}"})
    if sh in ("DEGRADED", "OFFLINE") and status in ("PREDICTED_FAILURE", "ABNORMAL"):
        evidence.append({"rule": "SENSOR_RELIABILITY", "detail": f"sensor health {sh}: treat with caution"})
    st.status, st.status_evidence, st.sensor_health, st.status_updated_at = status, {"evidence": evidence}, sh, now
    return {"station": st.station_name, "status": status, "sensor_health": sh}
