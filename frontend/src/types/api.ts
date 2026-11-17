export type StationStatus = "NORMAL" | "ABNORMAL" | "PREDICTED_FAILURE" | "OFFLINE" | "UNKNOWN";
export interface Page<T> { items: T[]; total: number; limit: number; offset: number }
export interface Latest { timestamp: string; motor_rpm: number | null; hydraulic_high_pressure: number | null; hydraulic_low_pressure: number | null;
  vibration: number | null; temperature: number | null; motor_current: number | null; material_load: number | null; belt_speed: number | null; data_quality_status: string }
export interface Station { id: string; station_name: string; position_meters: number; position_km: number; status: StationStatus; sensor_health: string;
  status_updated_at: string | null; latest: Latest | null; evidence: { rule: string; detail: string }[] }
export interface Summary { conveyor_status: string; conveyor_length_m: number; total_stations: number; healthy_stations: number; abnormal_stations: number;
  predicted_failure_stations: number; offline_stations: number; unknown_stations: number; active_anomalies: number; critical_alerts: number;
  vision_incidents: number; simulated_time: string; simulation_running: boolean }
export interface Anomaly { id: string; station_id: string; station_name: string; position_meters: number; anomaly_type: string; source: string; severity: string;
  description: string; evidence: Record<string, unknown>; detected_at: string; resolved_at: string | null; status: string }
export interface Prediction { id: string; station_id: string; station_name: string; position_meters: number; component: string; failure_type: string;
  risk_score: number; severity: string; estimated_time_to_failure_hours: number | null; prediction_basis: string; class_scores: Record<string, number>;
  predicted_at: string; risk_score_meaning: string }
export interface Detection { id: string; image_path: string; annotated_path: string | null; damage_type: string; confidence: number; bounding_box: number[] | null;
  belt_segment_id: string | null; belt_position: number | null; location_source: string; detector_kind: string; incident_id: string | null; is_repeat: boolean;
  observation_count: number; first_area: number; latest_area: number; detected_at: string; growth_ratio: number | null; confidence_meaning: string }
export interface Segment { id: string; position_meters: number; segment_health: number; pass_count: number; last_observed_at: string | null }
export interface Point { timestamp: string; data_quality_status: string; [k: string]: number | string | null }
export interface SimStatus { running: boolean; speed: number; tick: number; simulated_time: string; seed: number; step_seconds: number; length_m: number;
  station_modes: Record<string, string>; belt: { traveled_m: number; loops: number; segment_under_camera: string; n_segments: number } }
export interface Scenarios { anomalies: { cycle_structure: string[]; value_level: string[]; sensor_faults: string[] };
  degradations: Record<string, { component: string; failure_type: string }> }
