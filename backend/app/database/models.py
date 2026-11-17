from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def _id() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class Conveyor(Base):
    __tablename__ = "conveyors"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_id)
    code: Mapped[str] = mapped_column(String(32), unique=True)
    name: Mapped[str] = mapped_column(String(100))
    length_meters: Mapped[float] = mapped_column(Float)
    status: Mapped[str] = mapped_column(String(20), default="STOPPED")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    stations: Mapped[list["SensorStation"]] = relationship(back_populates="conveyor")


class SensorStation(Base):
    __tablename__ = "sensor_stations"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_id)
    conveyor_id: Mapped[str] = mapped_column(ForeignKey("conveyors.id"))
    station_name: Mapped[str] = mapped_column(String(20), unique=True)       # ST-001
    position_meters: Mapped[float] = mapped_column(Float)
    status: Mapped[str] = mapped_column(String(24), default="UNKNOWN")        # NORMAL/ABNORMAL/PREDICTED_FAILURE/OFFLINE/UNKNOWN
    status_evidence: Mapped[dict] = mapped_column(JSON, default=dict)         # why the health engine chose this status
    sensor_health: Mapped[str] = mapped_column(String(16), default="UNKNOWN")  # ONLINE/DEGRADED/OFFLINE/UNKNOWN
    status_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_processed_timestamp: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)  # inference watermark
    conveyor: Mapped[Conveyor] = relationship(back_populates="stations")


class SensorReading(Base):
    __tablename__ = "sensor_readings"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    station_id: Mapped[str] = mapped_column(ForeignKey("sensor_stations.id"))
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    motor_rpm: Mapped[float | None] = mapped_column(Float, nullable=True)
    hydraulic_high_pressure: Mapped[float | None] = mapped_column(Float, nullable=True)
    hydraulic_low_pressure: Mapped[float | None] = mapped_column(Float, nullable=True)
    vibration: Mapped[float | None] = mapped_column(Float, nullable=True)
    temperature: Mapped[float | None] = mapped_column(Float, nullable=True)
    motor_current: Mapped[float | None] = mapped_column(Float, nullable=True)
    material_load: Mapped[float | None] = mapped_column(Float, nullable=True)
    belt_speed: Mapped[float | None] = mapped_column(Float, nullable=True)
    data_quality_status: Mapped[str] = mapped_column(String(24), default="OK")
    data_quality_detail: Mapped[str | None] = mapped_column(String(200), nullable=True)
    __table_args__ = (Index("ix_reading_station_ts", "station_id", "timestamp"),)


class OperatingCycle(Base):
    __tablename__ = "operating_cycles"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)          # deterministic cycle id (idempotent upserts)
    station_id: Mapped[str] = mapped_column(ForeignKey("sensor_stations.id"))
    start_time: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    end_time: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    operating_mode_sequence: Mapped[str] = mapped_column(String(64))
    classification: Mapped[str] = mapped_column(String(16))
    category: Mapped[str] = mapped_column(String(32), default="NONE")
    __table_args__ = (Index("ix_cycle_station_start", "station_id", "start_time"),)


class Anomaly(Base):
    __tablename__ = "anomalies"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_id)
    station_id: Mapped[str] = mapped_column(ForeignKey("sensor_stations.id"))
    anomaly_type: Mapped[str] = mapped_column(String(40))
    source: Mapped[str] = mapped_column(String(24))                         # PAPER_APPROACH_2 | SIGNAL_RULE | DATA_QUALITY
    severity: Mapped[str] = mapped_column(String(10))
    description: Mapped[str] = mapped_column(Text)
    cycle_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    evidence: Mapped[dict] = mapped_column(JSON, default=dict)
    detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(10), default="ACTIVE")       # ACTIVE | RESOLVED
    __table_args__ = (Index("ix_anom_station_det", "station_id", "detected_at"),)


class FailurePrediction(Base):
    __tablename__ = "failure_predictions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_id)
    station_id: Mapped[str] = mapped_column(ForeignKey("sensor_stations.id"))
    component: Mapped[str] = mapped_column(String(32))
    failure_type: Mapped[str] = mapped_column(String(32))
    risk_score: Mapped[float] = mapped_column(Float)
    severity: Mapped[str] = mapped_column(String(10))
    estimated_time_to_failure: Mapped[float | None] = mapped_column(Float, nullable=True)   # hours
    prediction_basis: Mapped[str] = mapped_column(String(32), default="SIMULATED_DEGRADATION")
    class_scores: Mapped[dict] = mapped_column(JSON, default=dict)
    predicted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    __table_args__ = (Index("ix_pred_station_at", "station_id", "predicted_at"),
                      UniqueConstraint("station_id", "predicted_at", name="uq_pred_station_window"))   # idempotent re-runs


class BeltSegment(Base):
    __tablename__ = "belt_segments"
    id: Mapped[str] = mapped_column(String(16), primary_key=True)           # BS-017
    position_meters: Mapped[float] = mapped_column(Float, default=0.0)      # current position along conveyor (simulated)
    last_observed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    segment_health: Mapped[float] = mapped_column(Float, default=1.0)       # 1.0 undamaged .. 0.0 severely damaged
    pass_count: Mapped[int] = mapped_column(Integer, default=0)


class VisionDetection(Base):
    __tablename__ = "vision_detections"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_id)
    image_path: Mapped[str] = mapped_column(String(300))
    annotated_path: Mapped[str | None] = mapped_column(String(300), nullable=True)
    damage_type: Mapped[str] = mapped_column(String(24))
    confidence: Mapped[float] = mapped_column(Float)
    bounding_box: Mapped[list | None] = mapped_column(JSON, nullable=True)
    belt_segment_id: Mapped[str | None] = mapped_column(ForeignKey("belt_segments.id"), nullable=True)
    belt_position: Mapped[float | None] = mapped_column(Float, nullable=True)
    location_source: Mapped[str] = mapped_column(String(16), default="SIMULATED")   # SIMULATED | USER_SUPPLIED | UNKNOWN
    detector_kind: Mapped[str] = mapped_column(String(24), default="HEURISTIC_DEMO")
    bbox_area: Mapped[int] = mapped_column(Integer, default=0)
    incident_id: Mapped[str | None] = mapped_column(String(36), nullable=True)      # id of first observation (self for first)
    is_repeat: Mapped[bool] = mapped_column(Boolean, default=False)
    observation_count: Mapped[int] = mapped_column(Integer, default=1)             # kept on the incident (first) row
    first_area: Mapped[int] = mapped_column(Integer, default=0)
    latest_area: Mapped[int] = mapped_column(Integer, default=0)
    detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    __table_args__ = (Index("ix_vis_seg", "belt_segment_id", "damage_type"),)
