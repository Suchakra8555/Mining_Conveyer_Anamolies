"""Orchestrator: simulator -> validation -> SQLite -> ML inference -> health -> vision capture."""
from __future__ import annotations

import logging
import threading
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd
from sqlalchemy import delete, desc, select, update

from app.core.config import DATA_DIR, MODELS_DIR, Settings
from app.database.models import (Anomaly, BeltSegment, Conveyor, FailurePrediction, OperatingCycle, SensorReading,
                                 SensorStation, VisionDetection)
from app.database.session import init_db, make_engine, make_session_factory, session_scope
from app.ml.anomaly_detection.features import RAW
from app.ml.anomaly_detection.pipeline import AnomalyDetector
from app.ml.anomaly_detection.signal_checks import check_window
from app.ml.failure_prediction.features import CHANNELS as FC, window_features, to_minutes
from app.ml.failure_prediction.model import RISK_THRESHOLD, FailureModel
from app.simulator.engine import CHANNELS, ConveyorSimulator, from_epoch, to_epoch
from app.vision.detector import load_detector
from app.vision.tracker import BeltTracker
from . import health, vision_service
from .quality import QualityValidator

log = logging.getLogger("conveyor.pipeline")
ANOMALY_WINDOW_H = 6
FAIL_WINDOW_H = 36
CYCLE_ANOMALY_TTL = timedelta(hours=2)   # simulated time an operational cycle anomaly stays ACTIVE
SAMPLES = DATA_DIR / "vision" / "samples"


class Pipeline:
    def __init__(self, settings: Settings, engine=None):
        self.s = settings
        self.engine = engine or make_engine(settings.db_url)
        init_db(self.engine)
        self.Session = make_session_factory(self.engine)
        self.lock = threading.RLock()
        self.sim = ConveyorSimulator(settings.sim)
        self.sim.speed = settings.sim_speed
        self.validator = QualityValidator()
        self.tracker = BeltTracker(settings.sim.length_m)
        self.detector = load_detector(settings.vision_weights)
        self.anom_model = self._load(AnomalyDetector, MODELS_DIR / "anomaly_detection" / "state_classifier_xtree.joblib")
        self.fail_model = self._load(FailureModel, MODELS_DIR / "failure_prediction" / "failure_model.joblib")
        self.damaged_map: dict[int, list[str]] = {}
        self.station_ids: dict[str, str] = {}      # ST-001 -> uuid
        self.last_inference_tick = -1
        self.vision_log: list[dict] = []

    @staticmethod
    def _load(cls, path):
        try:
            return cls.load(path)
        except Exception as e:
            log.warning("model %s not loaded (%s); run the training scripts", path.name, e)
            return None

    # ------------------------------------------------------------------ setup
    def setup(self, start: datetime | None = None, warm_hours: float | None = None, demo_scenarios: bool = True):
        """(Re)create DB content and warm-start simulated history so the dashboard is populated immediately."""
        with self.lock:
            warm = self.s.warm_start_hours if warm_hours is None else warm_hours
            end = start or datetime.now(timezone.utc).replace(hour=12, minute=0, second=0, microsecond=0)
            self.sim.running = False
            self.sim.reset(start=end - timedelta(hours=warm))
            self.validator = QualityValidator()
            self.tracker = BeltTracker(self.s.sim.length_m)
            with session_scope(self.Session) as db:
                for m in (VisionDetection, BeltSegment, FailurePrediction, Anomaly, OperatingCycle, SensorReading, SensorStation, Conveyor):
                    db.execute(delete(m))
                cv = Conveyor(code=self.sim.cfg.conveyor_id, name="Mining Conveyor CV-001 (simulated)", length_meters=self.sim.cfg.length_m, status="RUNNING")
                db.add(cv); db.flush()
                for st in self.sim.stations:
                    row = SensorStation(conveyor_id=cv.id, station_name=st.station_id, position_meters=st.position_m)
                    db.add(row); db.flush(); self.station_ids[st.station_id] = row.id
                for i in range(self.tracker.n):
                    db.add(BeltSegment(id=BeltTracker.segment_id(i), position_meters=self.tracker.position_of(i)))
            rng = np.random.default_rng(self.s.sim.seed)
            segs = rng.choice(self.tracker.n, size=8, replace=False)
            self.damaged_map = {}
            if (SAMPLES / "annotations.json").exists():
                import json
                meta = json.loads((SAMPLES / "annotations.json").read_text())
                for k, d in zip(segs, meta["damaged_segments"]):
                    self.damaged_map[int(k)] = d["files"]
            if warm > 0:
                self._warm_start(warm, demo_scenarios)
            with session_scope(self.Session) as db:
                self._inference(db, force=True)
                self._health(db)

    def _warm_start(self, warm: float, demo: bool):
        t_end = self.sim.now + warm * 3600
        dp, ap = [], []
        if demo:
            t0 = self.sim.now
            dp = [{"station_id": "ST-004", "scenario": "bearing_degradation", "duration_h": warm * 2.2, "start": t0 - 0.2 * 3600 + 0.0, "shape": 1.3},
                  {"station_id": "ST-008", "scenario": "hydraulic_degradation", "duration_h": warm * 2.6, "start": t0, "shape": 1.0}]
            ap = [{"station_id": "ST-002", "kind": "EXCESSIVE_VIBRATION", "start": t_end - 1 * 3600, "duration_s": 3 * 3600},
                  {"station_id": "ST-003", "kind": "ABNORMAL_STARTUP", "start": t_end - 1.8 * 3600},
                  {"station_id": "ST-006", "kind": "UNEXPECTED_STOP", "start": t_end - 1.5 * 3600},
                  {"station_id": "ST-010", "kind": "SENSOR_DISCONNECT", "start": t_end - 1.0 * 3600, "duration_s": 3 * 3600}]
        feats, _truth = self.sim.generate_historical_dataset(from_epoch(self.sim.now), days=warm / 24.0, dt=60.0,
                                                             degradation_plan=dp, anomaly_plan=ap)
        # warm-start episodes begin at the beginning of the window; shift level so degradations are visible at "now"
        feats = feats.sort_values(["timestamp", "station_id"])
        rows = []
        with session_scope(self.Session) as db:
            for r in feats.itertuples(index=False):
                rows.append(self._reading_row(r.station_id, r.timestamp.to_pydatetime(), {c: getattr(r, c) for c in CHANNELS}))
            db.bulk_save_objects(rows)
            # integrate belt travel with ST-001 belt speed so segment passes are consistent
        b = feats[feats.station_id == "ST-001"]
        with session_scope(self.Session) as db:       # replay belt travel + camera captures over the warm-start history
            for ts, v in zip(b["timestamp"], b["belt_speed"]):
                if v == v and v > 0:
                    crossed = self.tracker.advance(float(v) * 60.0)
                    if crossed:
                        self._vision_capture(db, crossed, ts.to_pydatetime())
        self.sim.now = t_end
        self.sim.tick = int(warm * 60)

    def _reading_row(self, sid: str, ts: datetime, vals: dict) -> SensorReading:
        clean = {c: (None if (v is None or v != v) else float(v)) for c, v in vals.items()}
        status, detail = self.validator.validate(sid, ts, clean)
        return SensorReading(station_id=self.station_ids[sid], timestamp=ts, data_quality_status=status, data_quality_detail=detail, **clean)

    # ------------------------------------------------------------------- tick
    def tick(self) -> dict:
        with self.lock:
            readings = self.sim.step()
            now = from_epoch(self.sim.now)
            with session_scope(self.Session) as db:
                rows = []
                belt = []
                for r in readings:
                    vals = {c: r[c] for c in CHANNELS}
                    rows.append(self._reading_row(r["station_id"], r["timestamp"], vals))
                    if r["station_id"] == "ST-001" and r["belt_speed"] is not None:
                        belt.append(r["belt_speed"])
                db.add_all(rows)
                crossed = self.tracker.advance(float(np.mean(belt) if belt else 0.0) * self.sim.step_seconds)
                self._vision_capture(db, crossed, now)
                if (self.sim.tick - self.last_inference_tick) >= self.s.inference_every_n_ticks:
                    self._inference(db)
                self._health(db)
            return {"tick": self.sim.tick, "simulated_time": now.isoformat(), "readings": len(readings), "segments_crossed": len(crossed)}

    def _vision_capture(self, db, crossed: list[int], now):
        for idx in crossed:
            seg = db.get(BeltSegment, BeltTracker.segment_id(idx))
            seg.pass_count += 1; seg.last_observed_at = now; seg.position_meters = self.tracker.position_of(idx)
            files = self.damaged_map.get(idx)
            if files:
                stage = min((self.tracker.passes.get(idx, 1) - 1) // 2, 2)   # damage grows with successive passes (simulated wear)
                res = vision_service.analyze_and_store(db, self.detector, SAMPLES / files[stage], seg.id, seg.position_meters, now, "SIMULATED")
                self.vision_log.append({"segment": seg.id, "image": files[stage], "n": len(res)})

    # -------------------------------------------------------------- inference
    def _station_frame(self, db, sid_uuid: str, hours: float, until) -> pd.DataFrame:
        q = select(SensorReading).where(SensorReading.station_id == sid_uuid, SensorReading.timestamp >= until - timedelta(hours=hours),
                                        SensorReading.timestamp <= until).order_by(SensorReading.timestamp)
        rows = db.execute(q).scalars().all()
        df = pd.DataFrame([{**{c: getattr(r, c) for c in CHANNELS}, "timestamp": r.timestamp, "q": r.data_quality_status, "qd": r.data_quality_detail} for r in rows])
        if not df.empty:
            df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)   # SQLite returns naive datetimes (stored as UTC)
        return df

    @staticmethod
    def mask_bad(df: pd.DataFrame) -> pd.DataFrame:
        """Sensor-quality problems must not look like equipment problems: blank affected values."""
        if df.empty:
            return df
        df = df.copy()
        bad = df["q"].isin(["SPIKE", "OUT_OF_RANGE", "BAD_TIMESTAMP"])
        df.loc[bad, CHANNELS] = np.nan
        stuck = df["q"] == "STUCK"
        for i in df.index[stuck]:
            ch = (df.at[i, "qd"] or "").split(" ")[0]
            if ch in CHANNELS:
                df.at[i, ch] = np.nan
        return df

    def _inference(self, db, force=False):
        self.last_inference_tick = self.sim.tick
        now = from_epoch(self.sim.now)
        for st in db.execute(select(SensorStation)).scalars():
            sid = st.station_name
            raw = self.mask_bad(self._station_frame(db, st.id, FAIL_WINDOW_H, now))
            if raw.empty or len(raw) < 30:
                continue
            self._run_anomaly(db, st, raw[raw.timestamp >= now - timedelta(hours=ANOMALY_WINDOW_H)], now)
            self._run_failure(db, st, raw, now)
        # resolve stale cycle anomalies
        for a in db.execute(select(Anomaly).where(Anomaly.status == "ACTIVE", Anomaly.source == "PAPER_APPROACH_2")).scalars():
            if now - a.detected_at.replace(tzinfo=timezone.utc) > CYCLE_ANOMALY_TTL:
                a.status, a.resolved_at = "RESOLVED", now
        db.flush()   # autoflush is off: make new rows visible to the health engine in the same transaction

    def _run_anomaly(self, db, st, raw6h: pd.DataFrame, now):
        if self.anom_model is not None and len(raw6h) >= 30:
            results, _ = self.anom_model.detect(raw6h, st.station_name, complete_only=True)
            for c in results:
                cid = c.cycle_id
                if db.get(OperatingCycle, cid) is None:
                    db.add(OperatingCycle(id=cid, station_id=st.id, start_time=c.start.to_pydatetime(), end_time=c.end.to_pydatetime(),
                                          operating_mode_sequence=c.sequence, classification=c.classification, category=c.category))
                if c.classification == "ABNORMAL" and db.execute(select(Anomaly.id).where(Anomaly.cycle_id == cid)).first() is None:
                    ended = c.detected_at.to_pydatetime()
                    db.add(Anomaly(station_id=st.id, anomaly_type=c.category, source="PAPER_APPROACH_2", severity=c.severity,
                                   description=f"Abnormal duty cycle: observed state sequence '{c.sequence}' ({c.category.replace('_', ' ').lower()})",
                                   cycle_id=cid, evidence={"sequence": c.sequence, "cycle_start": str(c.start), "cycle_end": str(c.end)},
                                   detected_at=ended, status="ACTIVE" if now - ended <= CYCLE_ANOMALY_TTL else "RESOLVED",
                                   resolved_at=None if now - ended <= CYCLE_ANOMALY_TTL else ended + CYCLE_ANOMALY_TTL))
        # value-level rule checks on the last 30 minutes
        w = raw6h[raw6h.timestamp >= now - timedelta(minutes=30)]
        fired = {f["anomaly_type"]: f for f in check_window(w)}
        active = {a.anomaly_type: a for a in db.execute(select(Anomaly).where(Anomaly.station_id == st.id, Anomaly.status == "ACTIVE", Anomaly.source == "SIGNAL_RULE")).scalars()}
        for k, f in fired.items():
            if k not in active:
                db.add(Anomaly(station_id=st.id, anomaly_type=k, source="SIGNAL_RULE", severity=f["severity"], description=f["description"],
                               evidence={"value": f["value"]}, detected_at=now))
        for k, a in active.items():
            if k not in fired:
                a.status, a.resolved_at = "RESOLVED", now

    def _run_failure(self, db, st, raw: pd.DataFrame, now):
        if self.fail_model is None:
            return
        d = to_minutes(raw[["timestamp"] + FC])
        f = window_features(d, d.index[-1])
        if f is None:
            return
        X = pd.DataFrame([f])
        p = self.fail_model.predict(X)[0]
        db.add(FailurePrediction(station_id=st.id, component=p["component"], failure_type=p["failure_type"], risk_score=p["risk_score"],
                                 severity=p["severity"], estimated_time_to_failure=p["estimated_time_to_failure_hours"],
                                 prediction_basis=p["prediction_basis"], class_scores=p["class_scores"], predicted_at=now))

    def _health(self, db):
        now = from_epoch(self.sim.now)
        for st in db.execute(select(SensorStation)).scalars():
            health.evaluate_station(db, st, now, self.sim.step_seconds)

    # -------------------------------------------------------------- controls
    def run_inference_now(self):
        with self.lock, session_scope(self.Session) as db:
            self._inference(db, force=True)
            self._health(db)
