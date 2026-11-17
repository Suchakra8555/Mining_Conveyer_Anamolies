from __future__ import annotations

from datetime import datetime
from typing import Any, Generic, Optional, TypeVar

from pydantic import BaseModel, ConfigDict, Field

T = TypeVar("T")


class ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class Page(BaseModel, Generic[T]):
    items: list[T]
    total: int
    limit: int
    offset: int


class ConveyorOut(ORM):
    id: str; code: str; name: str; length_meters: float; status: str; created_at: datetime


class StationOut(ORM):
    id: str; station_name: str; position_meters: float; status: str; sensor_health: str
    status_updated_at: Optional[datetime] = None
    position_km: float = 0.0


class ReadingOut(ORM):
    timestamp: datetime
    motor_rpm: Optional[float] = None; hydraulic_high_pressure: Optional[float] = None; hydraulic_low_pressure: Optional[float] = None
    vibration: Optional[float] = None; temperature: Optional[float] = None; motor_current: Optional[float] = None
    material_load: Optional[float] = None; belt_speed: Optional[float] = None
    data_quality_status: str = "OK"


class AnomalyOut(ORM):
    id: str; station_id: str; station_name: str = ""; position_meters: float = 0.0
    anomaly_type: str; source: str; severity: str; description: str
    evidence: dict = Field(default_factory=dict)
    detected_at: datetime; resolved_at: Optional[datetime] = None; status: str


class PredictionOut(ORM):
    id: str; station_id: str; station_name: str = ""; position_meters: float = 0.0
    component: str; failure_type: str; risk_score: float; severity: str
    estimated_time_to_failure_hours: Optional[float] = None
    prediction_basis: str; class_scores: dict = Field(default_factory=dict); predicted_at: datetime
    risk_score_meaning: str = "model score (1 - P(NORMAL)); not a calibrated probability"


class VisionOut(ORM):
    id: str; image_path: str; annotated_path: Optional[str] = None; damage_type: str; confidence: float
    bounding_box: Optional[list] = None; belt_segment_id: Optional[str] = None; belt_position: Optional[float] = None
    location_source: str; detector_kind: str; incident_id: Optional[str] = None; is_repeat: bool
    observation_count: int; first_area: int; latest_area: int; detected_at: datetime
    growth_ratio: Optional[float] = None
    confidence_meaning: str = "heuristic score for HEURISTIC_DEMO; model confidence otherwise (neither is calibrated)"


class ScenarioRequest(BaseModel):
    type: str = Field(description="anomaly | degradation")
    station_id: str
    kind: str = Field(description="anomaly kind or degradation scenario name")
    duration: float = Field(default=1800, description="seconds for anomalies, hours for degradations")
    channel: Optional[str] = None


class SpeedRequest(BaseModel):
    speed: float = Field(gt=0, le=600)


class ResetRequest(BaseModel):
    warm_start_hours: float = Field(default=12, ge=0, le=72)
    seed: Optional[int] = None
    demo_scenarios: bool = True


class IngestReading(BaseModel):
    station_id: str
    timestamp: datetime
    motor_rpm: Optional[float] = None; hydraulic_high_pressure: Optional[float] = None; hydraulic_low_pressure: Optional[float] = None
    vibration: Optional[float] = None; temperature: Optional[float] = None; motor_current: Optional[float] = None
    material_load: Optional[float] = None; belt_speed: Optional[float] = None
