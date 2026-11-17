from __future__ import annotations

from fastapi import HTTPException, Request
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.database.models import Conveyor, SensorStation


def get_pipeline(request: Request):
    return request.app.state.pipeline


def get_db(request: Request):
    p = request.app.state.pipeline
    db = p.Session()
    try:
        yield db
    finally:
        db.close()


def station_or_404(db: Session, key: str) -> SensorStation:
    st = db.execute(select(SensorStation).where(or_(SensorStation.id == key, SensorStation.station_name == key))).scalars().first()
    if not st:
        raise HTTPException(404, f"station {key} not found")
    return st


def conveyor_or_404(db: Session, key: str) -> Conveyor:
    c = db.execute(select(Conveyor).where(or_(Conveyor.id == key, Conveyor.code == key))).scalars().first()
    if not c:
        raise HTTPException(404, f"conveyor {key} not found")
    return c
