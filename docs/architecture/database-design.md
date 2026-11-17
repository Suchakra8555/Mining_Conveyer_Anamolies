# Database design

SQLite through SQLAlchemy 2.0; Alembic revision `0001` mirrors the models. Image files stay on disk (`data/vision/`), the database stores paths.

```mermaid
erDiagram
    CONVEYOR ||--o{ SENSOR_STATION : contains
    SENSOR_STATION ||--o{ SENSOR_READING : produces
    SENSOR_STATION ||--o{ OPERATING_CYCLE : operates
    SENSOR_STATION ||--o{ ANOMALY : reports
    SENSOR_STATION ||--o{ FAILURE_PREDICTION : receives
    BELT_SEGMENT ||--o{ VISION_DETECTION : observed_in

    CONVEYOR { string id PK; string code; float length_meters; string status }
    SENSOR_STATION { string id PK; string conveyor_id FK; string station_name; float position_meters; string status; json status_evidence; string sensor_health }
    SENSOR_READING { int id PK; string station_id FK; datetime timestamp; float motor_rpm; float vibration; float temperature; string data_quality_status }
    OPERATING_CYCLE { string id PK; string station_id FK; datetime start_time; datetime end_time; string operating_mode_sequence; string classification; string category }
    ANOMALY { string id PK; string station_id FK; string anomaly_type; string source; string severity; datetime detected_at; string status }
    FAILURE_PREDICTION { string id PK; string station_id FK; string component; string failure_type; float risk_score; float estimated_time_to_failure; datetime predicted_at }
    BELT_SEGMENT { string id PK; float position_meters; float segment_health; int pass_count }
    VISION_DETECTION { string id PK; string belt_segment_id FK; string damage_type; float confidence; string location_source; string incident_id; bool is_repeat; int observation_count }
```

Differences from the PRD's list, all additive: `SensorStation.status_evidence` / `sensor_health` / `status_updated_at` (health engine output); `SensorReading.data_quality_detail`; `OperatingCycle.category`; `Anomaly.source`, `cycle_id`, `evidence`; `FailurePrediction.class_scores`; `BeltSegment.pass_count`; `VisionDetection` fields for the annotated image, location source, detector kind, area tracking and incident grouping (`incident_id` points at the first observation, `is_repeat` marks later ones). Primary keys are UUID strings except `SensorReading.id` (integer, for insert speed) and `OperatingCycle.id` / `BeltSegment.id` (deterministic strings so re-running inference is idempotent).

Indexes: `(station_id, timestamp)` on readings, `(station_id, start_time)` on cycles, `(station_id, detected_at)` on anomalies, `(station_id, predicted_at)` on predictions, `(belt_segment_id, damage_type)` on detections.

SQLite stores timestamps without a time zone; everything is UTC and the code re-attaches UTC when reading back into pandas.
