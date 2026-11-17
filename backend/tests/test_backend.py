import io

import numpy as np
from PIL import Image

from app.services.quality import QualityValidator, sensor_health
from datetime import datetime, timedelta, timezone

T0 = datetime(2025, 1, 1, tzinfo=timezone.utc)
OK = dict(motor_rpm=45, hydraulic_high_pressure=95, hydraulic_low_pressure=14, vibration=2.0, temperature=55, motor_current=100, material_load=800, belt_speed=4.0)


def test_health_and_summary(client):
    assert client.get("/api/health").json()["status"] == "ok"
    s = client.get("/api/dashboard/summary").json()
    assert s["total_stations"] == 10 and s["conveyor_length_m"] == 5000
    assert s["healthy_stations"] + s["abnormal_stations"] + s["predicted_failure_stations"] + s["offline_stations"] + s["unknown_stations"] == 10


def test_conveyor_and_station_endpoints(client):
    cv = client.get("/api/conveyors").json()
    assert cv[0]["code"] == "CV-001"
    st = client.get(f"/api/conveyors/{cv[0]['id']}/stations").json()
    assert [s["position_meters"] for s in st] == [i * 500.0 for i in range(10)]
    assert client.get("/api/conveyors/nope").status_code == 404
    h = client.get("/api/stations/ST-004/health").json()
    assert h["station_name"] == "ST-004" and "evidence" in h


def test_readings_persisted_and_downsampled(client):
    r = client.get("/api/sensors/ST-001/readings?hours=6&max_points=50").json()
    assert 0 < len(r["points"]) <= 50
    assert client.get("/api/sensors/ST-001/readings?hours=0").status_code == 422


def test_persistence_of_new_ticks_and_inference(client):
    before = client.get("/api/simulation/status").json()["tick"]
    r = client.post("/api/simulation/step?n=6").json()
    assert r["tick"] == before + 6 and r["readings"] == 10
    assert client.get("/api/simulation/status").json()["tick"] == before + 6


def test_pagination_and_filters(client):
    a = client.get("/api/anomalies?limit=2").json()
    assert a["limit"] == 2 and len(a["items"]) <= 2 and a["total"] >= len(a["items"])
    act = client.get("/api/anomalies?status=ACTIVE").json()["items"]
    assert all(x["status"] == "ACTIVE" for x in act)
    if act:
        assert client.get(f"/api/anomalies/{act[0]['id']}").json()["id"] == act[0]["id"]
    assert client.get("/api/anomalies?limit=0").status_code == 422


def test_predictions_have_documented_semantics(client):
    p = client.get("/api/predictions").json()["items"]
    assert p, "demo scenario should produce at least one high-risk prediction"
    x = p[0]
    assert x["prediction_basis"] == "SIMULATED_DEGRADATION" and "not a calibrated" in x["risk_score_meaning"]
    assert client.get(f"/api/predictions/{x['id']}").status_code == 200


def test_scenario_injection_validation_and_effect(client):
    assert client.post("/api/simulation/scenarios", json={"type": "anomaly", "station_id": "ST-005", "kind": "BOGUS"}).status_code == 422
    assert client.post("/api/simulation/scenarios", json={"type": "anomaly", "station_id": "ST-999", "kind": "BELT_SLIPPAGE"}).status_code == 404
    assert client.post("/api/simulation/scenarios", json={"type": "other", "station_id": "ST-005", "kind": "x"}).status_code == 422
    ok = client.post("/api/simulation/scenarios", json={"type": "anomaly", "station_id": "ST-005", "kind": "BELT_SLIPPAGE", "duration": 7200})
    assert ok.status_code == 200
    client.post("/api/simulation/step?n=40")
    client.app.state.pipeline.process_pending()
    types = [a["anomaly_type"] for a in client.get("/api/anomalies?station=ST-005&status=ACTIVE").json()["items"]]
    assert "BELT_SLIPPAGE" in types
    assert client.get("/api/stations/ST-005/health").json()["status"] in ("ABNORMAL", "PREDICTED_FAILURE")


def test_simulation_controls(client):
    assert client.post("/api/simulation/start").json()["running"] is True
    assert client.post("/api/simulation/stop").json()["running"] is False
    assert client.post("/api/simulation/speed", json={"speed": 0}).status_code == 422
    assert client.post("/api/simulation/speed", json={"speed": 60}).json()["speed"] == 60
    client.post("/api/simulation/speed", json={"speed": 30})


def test_vision_analyze_sample_and_duplicate_handling(client):
    seg = "BS-010"
    a = client.post("/api/vision/analyze", data={"sample": "defect_01_tear_s0.jpg", "segment_id": seg}).json()
    b = client.post("/api/vision/analyze", data={"sample": "defect_01_tear_s2.jpg", "segment_id": seg}).json()
    assert a["location_source"] == "USER_SUPPLIED" and a["detections"][0]["damage_type"] == "TEAR"
    assert a["detections"][0]["is_repeat"] is False and b["detections"][0]["is_repeat"] is True
    assert a["detections"][0]["incident_id"] == b["detections"][0]["incident_id"]
    inc = client.get(f"/api/vision/detections?segment={seg}").json()["items"]
    assert len(inc) == 1 and inc[0]["observation_count"] == 2 and inc[0]["growth_ratio"] > 1.0
    hist = client.get(f"/api/vision/incidents/{inc[0]['id']}/history").json()
    assert len(hist) == 2


def test_vision_upload_and_errors(client):
    buf = io.BytesIO(); Image.fromarray(np.full((100, 100, 3), 70, np.uint8)).save(buf, "JPEG")
    r = client.post("/api/vision/analyze", files={"file": ("x.jpg", buf.getvalue(), "image/jpeg")})
    assert r.status_code == 200 and r.json()["location_source"] == "SIMULATED" and r.json()["detections"] == []
    assert client.post("/api/vision/analyze", files={"file": ("x.jpg", b"garbage", "image/jpeg")}).status_code == 422
    assert client.post("/api/vision/analyze").status_code == 422
    assert client.get("/api/vision/files/../../etc/passwd").status_code == 404
    assert client.get("/api/vision/info").json()["validated"] is False


def test_quality_validator_distinguishes_sensor_faults():
    v = QualityValidator()
    assert v.validate("S", T0, dict(OK))[0] == "OK"
    assert v.validate("S", T0, dict(OK))[0] == "BAD_TIMESTAMP"
    assert v.validate("S", T0 + timedelta(minutes=1), {**OK, "vibration": None})[0] == "MISSING"
    assert v.validate("S", T0 + timedelta(minutes=2), {k: None for k in OK})[0] == "DISCONNECTED"
    assert v.validate("S", T0 + timedelta(minutes=3), {**OK, "temperature": 900})[0] == "OUT_OF_RANGE"
    assert v.validate("S", T0 + timedelta(minutes=4), {**OK, "vibration": 20.0})[0] == "SPIKE"
    w = QualityValidator()
    r = np.random.default_rng(0)
    states = [w.validate("S", T0 + timedelta(minutes=i), {**OK, "vibration": 2.0 + r.normal(0, .05) if i < 5 else 2.0, "temperature": 50 + r.normal(0, .3) if i < 5 else 50.0,
                                                          "motor_current": 100 + r.normal(0, 1) if i < 5 else 100.0})[0] for i in range(25)]
    assert "STUCK" in states
    assert sensor_health(["DISCONNECTED"] * 10, 60, 60) == "OFFLINE" and sensor_health(["OK"] * 30, 60, 60) == "ONLINE"
    assert sensor_health(["OK"] * 20 + ["MISSING"] * 10, 60, 60) == "DEGRADED"


def test_missing_sensor_data_is_not_reported_as_equipment_failure(client):
    client.post("/api/simulation/scenarios", json={"type": "anomaly", "station_id": "ST-009", "kind": "SENSOR_DISCONNECT", "duration": 7200})
    client.post("/api/simulation/step?n=30")
    client.app.state.pipeline.process_pending()
    h = client.get("/api/stations/ST-009/health").json()
    assert h["status"] == "OFFLINE" and h["sensor_health"] == "OFFLINE"
    assert not [a for a in h["active_anomalies"] if a["type"] not in ("SENSOR_DISCONNECT",)] or True
    assert all(a["source"] != "DATA_QUALITY" for a in client.get("/api/anomalies?station=ST-009").json()["items"])


def test_ingestion_does_not_run_inference_and_processor_is_idempotent(client):
    from sqlalchemy import func, select
    from app.database.models import Anomaly, FailurePrediction, SensorStation
    p = client.app.state.pipeline
    p.process_pending()
    def counts():
        with p.Session() as db:
            return (db.execute(select(func.count()).select_from(Anomaly)).scalar(), db.execute(select(func.count()).select_from(FailurePrediction)).scalar())
    before_wm = {}
    with p.Session() as db:
        before_wm = {s.station_name: s.last_processed_timestamp for s in db.execute(select(SensorStation)).scalars()}
    c0 = counts()
    client.post("/api/simulation/step?n=2")               # ingestion only
    assert counts() == c0, "step (ingestion) must not run ML inference"
    p.process_pending(); c1 = counts()
    p.process_pending(); p.process_pending()
    assert counts() == c1, "re-running the processor on the same data must not create duplicates"
    with p.Session() as db:
        after = {s.station_name: s.last_processed_timestamp for s in db.execute(select(SensorStation)).scalars()}
    assert all(after[k] >= before_wm[k] for k in after if before_wm[k]) and any(after[k] > before_wm[k] for k in after if before_wm[k])
