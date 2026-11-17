"""Conveyor sensor simulator.

Design: each station owns a *schedule* of operating-mode segments (OFF/IDLE/OPERATIONAL/ACTIVE).
Sensor values are a deterministic function of (schedule, time) plus seeded noise, so the same code path
serves both live stepping (n=1 timestamps) and vectorised historical generation.

Ground truth (modes, cycle kinds, anomaly windows, degradation levels, failure times) is kept in a
separate structure and returned as a separate DataFrame; it is never part of the feature columns.
"""
from __future__ import annotations

import math
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

import numpy as np
import pandas as pd

from app.core.config import SimConfig

DAY = 86400.0


class Mode(int, Enum):
    OFF = 0
    IDLE = 1
    OPERATIONAL = 2   # transitional running state (ramp up / ramp down)  -> paper state "C"
    ACTIVE = 3        # steady loaded operation                           -> paper state "D"


# Mapping to the research paper's state letters (A: off, B: idle, C: transition, D: steady).
MODE_LETTER = {Mode.OFF: "A", Mode.IDLE: "B", Mode.OPERATIONAL: "C", Mode.ACTIVE: "D"}

NORMAL_TRANSITIONS = {
    Mode.OFF: {Mode.IDLE},
    Mode.IDLE: {Mode.OPERATIONAL, Mode.OFF},
    Mode.OPERATIONAL: {Mode.ACTIVE, Mode.IDLE},
    Mode.ACTIVE: {Mode.OPERATIONAL},
}
# Transitions that only occur in abnormal behaviour (used for testing/injection)
ABNORMAL_TRANSITIONS = {(Mode.ACTIVE, Mode.OFF), (Mode.IDLE, Mode.ACTIVE), (Mode.OPERATIONAL, Mode.OFF)}


def is_valid_transition(a: Mode, b: Mode) -> bool:
    return b in NORMAL_TRANSITIONS[a]


CHANNELS = ["motor_rpm", "hydraulic_high_pressure", "hydraulic_low_pressure", "vibration",
            "temperature", "motor_current", "material_load", "belt_speed"]
PAPER_CHANNELS = ["motor_rpm", "hydraulic_high_pressure", "hydraulic_low_pressure"]  # + differential (derived)
EXTENDED_CHANNELS = ["vibration", "temperature", "motor_current", "material_load", "belt_speed"]

CYCLE_ANOMALY_KINDS = ["UNEXPECTED_STOP", "ABNORMAL_STARTUP", "INTERMITTENT_OPERATION"]
VALUE_ANOMALY_KINDS = ["MOTOR_OVERLOAD", "HYDRAULIC_FLUCTUATION", "EXCESSIVE_VIBRATION",
                       "BELT_SLIPPAGE", "EXCESSIVE_TEMPERATURE"]
SENSOR_FAULT_KINDS = ["SENSOR_STUCK", "SENSOR_SPIKE", "SENSOR_DISCONNECT", "SENSOR_DROPOUT"]

# scenario -> (component, failure_type)
DEGRADATION = {
    "bearing_degradation": ("BEARING", "EXCESSIVE_WEAR"),
    "pulley_degradation": ("PULLEY", "LAGGING_WEAR"),
    "idler_deterioration": ("IDLER", "ROLLER_SEIZURE"),
    "belt_tension_degradation": ("CONVEYOR_BELT", "TENSION_LOSS"),
    "belt_abrasion": ("CONVEYOR_BELT", "SURFACE_ABRASION"),
    "motor_overheating": ("DRIVE_MOTOR", "OVERHEATING"),
    "hydraulic_degradation": ("HYDRAULIC_SYSTEM", "PRESSURE_LOSS"),
}


@dataclass
class Seg:
    t0: float
    t1: float
    mode: Mode
    cycle_id: Optional[str] = None
    kind: str = "NORMAL"  # NORMAL or one of CYCLE_ANOMALY_KINDS


@dataclass
class AnomalyWindow:
    kind: str
    t0: float
    t1: float
    channel: Optional[str] = None
    stuck_value: Optional[float] = None


@dataclass
class DegEpisode:
    scenario: str
    t0: float
    fail_t: float
    shape: float = 1.5

    def level(self, t: np.ndarray) -> np.ndarray:
        x = np.clip((t - self.t0) / max(self.fail_t - self.t0, 1.0), 0.0, 1.0)
        lv = x ** self.shape
        return np.where((t >= self.t0) & (t <= self.fail_t), lv, 0.0)


@dataclass
class Station:
    idx: int
    station_id: str          # ST-001
    uuid: str
    position_m: float
    segs: list = field(default_factory=list)
    anomalies: list = field(default_factory=list)
    episodes: list = field(default_factory=list)
    bias: dict = field(default_factory=dict)
    health_status: str = "UNKNOWN"
    cycle_counter: int = 0

    @property
    def horizon(self) -> float:
        return self.segs[-1].t1 if self.segs else 0.0

    @property
    def position_km(self) -> float:
        return self.position_m / 1000.0


def to_epoch(dt: datetime) -> float:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.timestamp()


def from_epoch(t: float) -> datetime:
    return datetime.fromtimestamp(t, tz=timezone.utc)


class ConveyorSimulator:
    def __init__(self, config: SimConfig | None = None, start: datetime | None = None):
        self.cfg = config or SimConfig()
        self._start = start or datetime(2025, 1, 1, 0, 0, tzinfo=timezone.utc)
        self.running = False
        self.speed = 30.0                     # simulated seconds advanced per second of interval_s => see step_seconds
        self.reset(start=self._start)

    # ------------------------------------------------------------------ setup
    def reset(self, start: datetime | None = None, seed: int | None = None):
        if seed is not None:
            self.cfg = self.cfg.with_(seed=seed)
        if start is not None:
            self._start = start
        self.t0 = to_epoch(self._start)
        self.now = self.t0
        self.tick = 0
        self.rng = np.random.default_rng(self.cfg.seed)
        self.stations: list[Station] = []
        n = self.cfg.n_stations
        spacing = self.cfg.length_m / n
        for i in range(n):
            st = Station(idx=i, station_id=f"ST-{i + 1:03d}",
                         uuid=str(uuid.uuid5(uuid.NAMESPACE_DNS, f"{self.cfg.conveyor_id}-ST-{i + 1:03d}")),
                         position_m=i * spacing)
            r = np.random.default_rng([self.cfg.seed, 7, i])
            st.bias = {"motor_rpm": r.normal(0, 0.003), "hydraulic_high_pressure": r.normal(0, 0.015),
                       "hydraulic_low_pressure": r.normal(0, 0.015), "temperature": r.normal(0, 0.8)}
            self.stations.append(st)
        self.truth_log: list[dict] = []

    def get_station(self, station_id: str) -> Station:
        for s in self.stations:
            if s.station_id == station_id:
                return s
        raise KeyError(station_id)

    # --------------------------------------------------------------- schedule
    def _rng_sched(self, st: Station) -> np.random.Generator:
        return np.random.default_rng([self.cfg.seed, 11, st.idx, st.cycle_counter, len(st.segs)])

    def _add(self, st: Station, mode: Mode, dur_s: float, cycle_id=None, kind="NORMAL"):
        t0 = st.horizon if st.segs else self.t0 - 3600.0
        st.segs.append(Seg(t0, t0 + dur_s, mode, cycle_id, kind))

    def _new_cycle_id(self, st: Station) -> str:
        st.cycle_counter += 1
        return f"{st.station_id}-C{st.cycle_counter:05d}"

    def _build_cycle(self, st: Station, kind: str, r: np.random.Generator):
        """Append a duty cycle (without leading idle gap). Normal = B C D C B pattern."""
        cid = self._new_cycle_id(st)
        m = 60.0
        ramp = lambda: r.uniform(3, 5) * m
        if kind == "NORMAL":
            self._add(st, Mode.OPERATIONAL, ramp(), cid, kind)
            self._add(st, Mode.ACTIVE, r.uniform(25, 100) * m, cid, kind)
            self._add(st, Mode.OPERATIONAL, ramp(), cid, kind)
        elif kind == "UNEXPECTED_STOP":     # power lost while running; machine goes OFF (not idle)
            self._add(st, Mode.OPERATIONAL, ramp(), cid, kind)
            self._add(st, Mode.ACTIVE, r.uniform(10, 40) * m, cid, kind)
            self._add(st, Mode.OFF, r.uniform(15, 30) * m, None, "NORMAL")
        elif kind == "ABNORMAL_STARTUP":    # jumps from idle straight to full operation
            self._add(st, Mode.ACTIVE, r.uniform(20, 60) * m, cid, kind)
            self._add(st, Mode.OPERATIONAL, ramp(), cid, kind)
        elif kind == "INTERMITTENT_OPERATION":
            self._add(st, Mode.OPERATIONAL, ramp(), cid, kind)
            for _ in range(int(r.integers(2, 4))):
                self._add(st, Mode.ACTIVE, r.uniform(5, 12) * m, cid, kind)
                self._add(st, Mode.OPERATIONAL, ramp(), cid, kind)
        else:
            raise ValueError(kind)
        return cid

    def _extend(self, st: Station, until: float):
        """Lazily extend the schedule to cover `until`."""
        if not st.segs:
            self._add(st, Mode.OFF, 3600.0)
        while st.horizon < until + 3600.0:
            r = self._rng_sched(st)
            t = st.horizon
            day = math.floor(t / DAY) * DAY
            w0 = day + self.cfg.window_start_hour * 3600
            w1 = w0 + self.cfg.operating_hours * 3600
            last = st.segs[-1].mode
            if t < w0:
                self._add(st, Mode.OFF, w0 - t)
            elif t < w1 - 3600:
                if last == Mode.OFF:
                    self._add(st, Mode.IDLE, r.uniform(10, 20) * 60)
                else:
                    if last != Mode.IDLE:
                        self._add(st, Mode.IDLE, r.uniform(10, 20) * 60)
                    self._add(st, Mode.IDLE, r.uniform(10, 35) * 60)
                    kind = "NORMAL"
                    if r.random() < self.cfg.abnormal_cycle_prob:
                        kind = CYCLE_ANOMALY_KINDS[int(r.integers(0, len(CYCLE_ANOMALY_KINDS)))]
                    self._build_cycle(st, kind, r)
                    if st.segs[-1].mode != Mode.OFF:
                        self._add(st, Mode.IDLE, 12 * 60)
            else:
                if last not in (Mode.OFF, Mode.IDLE):
                    self._add(st, Mode.IDLE, 12 * 60)
                nxt = day + DAY + self.cfg.window_start_hour * 3600
                self._add(st, Mode.OFF, max(nxt - st.horizon, 60.0))

    def current_mode(self, st: Station, t: float | None = None) -> Mode:
        t = self.now if t is None else t
        self._extend(st, t)
        for s in reversed(st.segs):
            if s.t0 <= t < s.t1:
                return s.mode
        return Mode.OFF

    # --------------------------------------------------------------- injection
    def inject_anomaly(self, station_id: str, kind: str, duration_s: float = 1800.0,
                       channel: str | None = None, start: float | None = None) -> dict:
        kind = kind.upper()
        st = self.get_station(station_id)
        t = self.now if start is None else start
        if kind in CYCLE_ANOMALY_KINDS:
            self._extend(st, t)
            mode = self.current_mode(st, t)
            if kind == "UNEXPECTED_STOP" and mode in (Mode.ACTIVE, Mode.OPERATIONAL):
                self._truncate(st, t)
                cur = st.segs[-1]
                cur.kind = kind                     # the cycle in progress becomes the abnormal one
                for s in st.segs:
                    if s.cycle_id == cur.cycle_id:
                        s.kind = kind
                self._add(st, Mode.OFF, 20 * 60)
            else:
                # begin at the end of the current cycle / immediately if not running
                if mode in (Mode.ACTIVE, Mode.OPERATIONAL):
                    cid = [s for s in st.segs if s.t0 <= t < s.t1][0].cycle_id
                    end = max(s.t1 for s in st.segs if s.cycle_id == cid)
                    self._truncate(st, end)
                else:
                    self._truncate(st, t)
                if st.segs[-1].mode == Mode.OFF:
                    self._add(st, Mode.IDLE, 12 * 60)
                elif st.segs[-1].mode != Mode.IDLE:
                    self._add(st, Mode.IDLE, 12 * 60)
                self._add(st, Mode.IDLE, 12 * 60)
                self._build_cycle(st, kind, self._rng_sched(st))
                if st.segs[-1].mode != Mode.OFF:
                    self._add(st, Mode.IDLE, 12 * 60)
            return {"station_id": station_id, "kind": kind, "start": from_epoch(t).isoformat()}
        if kind in VALUE_ANOMALY_KINDS or kind in SENSOR_FAULT_KINDS:
            w = AnomalyWindow(kind, t, t + duration_s, channel)
            if kind == "SENSOR_STUCK":
                w.channel = channel or "vibration"
                w.stuck_value = float(self._render(st, np.array([t]), clean=True)[w.channel][0])
            st.anomalies.append(w)
            return {"station_id": station_id, "kind": kind, "start": from_epoch(t).isoformat(),
                    "end": from_epoch(t + duration_s).isoformat()}
        raise ValueError(f"unknown anomaly kind {kind}")

    def _truncate(self, st: Station, t: float):
        keep = []
        for s in st.segs:
            if s.t1 <= t:
                keep.append(s)
            elif s.t0 < t:
                s.t1 = t
                keep.append(s)
        st.segs = keep
        if not st.segs:
            self._add(st, Mode.OFF, 60.0)

    def inject_degradation(self, station_id: str, scenario: str, duration_h: float = 24.0,
                           start: float | None = None, shape: float = 1.5) -> dict:
        scenario = scenario.lower()
        if scenario not in DEGRADATION:
            raise ValueError(f"unknown degradation scenario {scenario}")
        st = self.get_station(station_id)
        t = self.now if start is None else start
        ep = DegEpisode(scenario, t, t + duration_h * 3600.0, shape)
        st.episodes.append(ep)
        comp, ftype = DEGRADATION[scenario]
        return {"station_id": station_id, "scenario": scenario, "component": comp, "failure_type": ftype,
                "start": from_epoch(t).isoformat(), "failure_time": from_epoch(ep.fail_t).isoformat()}

    # ------------------------------------------------------------------ render
    def _amb(self, t: np.ndarray) -> np.ndarray:
        return 28.0 + 6.0 * np.sin(2 * np.pi * ((t % DAY) / 3600.0 - 9.0) / 24.0)

    def _render(self, st: Station, times: np.ndarray, rng: np.random.Generator | None = None,
                clean: bool = False, return_truth: bool = False):
        cfg = self.cfg
        n = len(times)
        self._extend(st, float(times.max()))
        starts = np.array([s.t0 for s in st.segs])
        ends = np.array([s.t1 for s in st.segs])
        modes = np.array([int(s.mode) for s in st.segs])
        idx = np.clip(np.searchsorted(starts, times, side="right") - 1, 0, len(st.segs) - 1)
        pidx = np.clip(idx - 1, 0, len(st.segs) - 1)
        cur, prev = modes[idx], modes[pidx]
        into = times - starts[idx]
        u = np.clip(into / np.maximum(ends[idx] - starts[idx], 1.0), 0, 1)

        def ramped(table, ramp_s):
            c = np.array(table, dtype=float)[cur]
            p = np.array(table, dtype=float)[prev]
            f = np.clip(into / ramp_s, 0, 1)
            f = np.where(idx == 0, 1.0, f)
            return p + (c - p) * f

        nom = cfg.nominal_rpm
        # load profile inside ACTIVE: loading -> transport -> unloading
        load_active = np.where(u < 0.12, 0.15 + (0.75 - 0.15) * (u / 0.12),
                      np.where(u > 0.88, 0.75 - (0.75 - 0.2) * ((u - 0.88) / 0.12),
                               0.75 + 0.15 * np.sin(2 * np.pi * times / 5400.0 + st.idx)))
        load_t = np.where(cur == int(Mode.ACTIVE), load_active, np.where(cur == int(Mode.OPERATIONAL), 0.1, 0.0))
        f_fast = np.clip(into / 20.0, 0, 1)
        f_fast = np.where(idx == 0, 1.0, f_fast)
        prev_load = np.where(prev == int(Mode.ACTIVE), 0.2, np.where(prev == int(Mode.OPERATIONAL), 0.1, 0.0))
        load = prev_load + (load_t - prev_load) * f_fast
        rpm = ramped([0.0, 0.4, 0.5 * nom, nom], 20.0)
        powered = ramped([0.0, 1.0, 1.0, 1.0], 20.0)
        thermal = ramped([0.0, 2.0, 8.0, 16.0], 900.0) + 6.0 * np.where(cur == int(Mode.ACTIVE), load, 0.0)

        # --- anomaly / degradation effects (physical, applied before sensor effects)
        slip = np.zeros(n)
        vib_add = np.zeros(n)
        temp_add = np.zeros(n)
        cur_mult = np.ones(n)
        hp_add = np.zeros(n)
        lp_add = np.zeros(n)
        hp_noise = np.zeros(n)
        rpm_mult = np.ones(n)
        load_extra = np.zeros(n)
        deg_level = np.zeros(n)
        deg_name = np.array([""] * n, dtype=object)
        fail_t = np.full(n, np.nan)
        anom_kind = np.array([""] * n, dtype=object)
        sensor_kind = np.array([""] * n, dtype=object)
        sf = rpm / nom
        for ep in st.episodes:
            L = ep.level(times)
            if not np.any(L > 0):
                continue
            run = np.clip(sf, 0, 1)
            sc = ep.scenario
            if sc == "bearing_degradation":
                vib_add += 5.0 * L ** 1.2 * run; temp_add += 22 * L * run; cur_mult += 0.04 * L
            elif sc == "pulley_degradation":
                vib_add += 2.4 * L * run; cur_mult += 0.12 * L; temp_add += 6 * L * run; slip += 0.01 * L
            elif sc == "idler_deterioration":
                vib_add += 3.0 * L * run; cur_mult += 0.05 * L
            elif sc == "belt_tension_degradation":
                slip += 0.10 * L; lp_add -= 5 * L; cur_mult += 0.03 * L
            elif sc == "belt_abrasion":
                slip += 0.025 * L; vib_add += 1.0 * L * run; cur_mult += 0.02 * L
            elif sc == "motor_overheating":
                temp_add += 45 * L ** 1.2 * run; cur_mult += 0.18 * L; rpm_mult -= 0.02 * L
            elif sc == "hydraulic_degradation":
                hp_add -= 25 * L; lp_add -= 4 * L; hp_noise += 6 * L
            better = L > deg_level
            deg_level = np.where(better, L, deg_level)
            deg_name = np.where(better, sc, deg_name)
            fail_t = np.where(better, ep.fail_t, fail_t)
        for w in st.anomalies:
            m = (times >= w.t0) & (times < w.t1)
            if not m.any():
                continue
            k = w.kind
            if k == "MOTOR_OVERLOAD":
                load_extra += np.where(m, 0.35, 0.0); rpm_mult -= np.where(m, 0.08, 0.0)
                temp_add += np.where(m, 10, 0.0); anom_kind = np.where(m, k, anom_kind)
            elif k == "HYDRAULIC_FLUCTUATION":
                hp_add += np.where(m, 12 * np.sin(2 * np.pi * times / 45.0), 0.0)
                lp_add += np.where(m, 3 * np.sin(2 * np.pi * times / 31.0), 0.0)
                hp_noise += np.where(m, 3.0, 0.0); anom_kind = np.where(m, k, anom_kind)
            elif k == "EXCESSIVE_VIBRATION":
                vib_add += np.where(m, 4.0 * np.clip(sf, 0.2, 1), 0.0); anom_kind = np.where(m, k, anom_kind)
            elif k == "BELT_SLIPPAGE":
                slip += np.where(m, 0.15, 0.0); anom_kind = np.where(m, k, anom_kind)
            elif k == "EXCESSIVE_TEMPERATURE":
                temp_add += np.where(m, 25, 0.0); anom_kind = np.where(m, k, anom_kind)
            else:
                sensor_kind = np.where(m, k, sensor_kind)

        lf = np.clip(load + load_extra, 0, 1.4)
        rpm = rpm * rpm_mult
        sf = rpm / nom
        r = rng if rng is not None else np.random.default_rng([cfg.seed, 3, st.idx, int(times[0])])
        ns = 0.0 if clean else cfg.noise_scale
        g = lambda s: r.normal(0, s * ns, n)
        b = st.bias
        out = {}
        out["motor_rpm"] = np.clip((rpm + g(0.25) * (powered > 0.5)) * (1 + b["motor_rpm"]), 0, None)
        out["hydraulic_high_pressure"] = np.clip(
            (powered * (30 + 55 * sf + 18 * lf) + hp_add + g(0.8) + r.normal(0, 1, n) * hp_noise * ns * powered)
            * (1 + b["hydraulic_high_pressure"]), 0, None)
        out["hydraulic_low_pressure"] = np.clip(
            (powered * (9 + 5 * sf) + lp_add * powered + g(0.25)) * (1 + b["hydraulic_low_pressure"]), 0, None)
        out["vibration"] = np.clip(0.1 + powered * (0.5 + 1.4 * sf) + 0.3 * lf + vib_add + g(0.08), 0, None)
        out["temperature"] = self._amb(times) + 1.5 * powered + thermal + temp_add + b["temperature"] + g(0.3)
        out["motor_current"] = np.clip(powered * (6 + 25 * sf + 95 * lf * sf) * cur_mult + g(1.0) * powered, 0, None)
        out["material_load"] = np.clip(lf * 1000.0 + g(10.0) * (lf > 0.01), 0, None)
        out["belt_speed"] = np.clip(rpm * (cfg.nominal_belt_speed_ms / nom) * (1 - slip) + g(0.02) * (rpm > 1), 0, None)

        if not clean:
            for w in st.anomalies:
                m = (times >= w.t0) & (times < w.t1)
                if not m.any():
                    continue
                if w.kind == "SENSOR_STUCK":
                    out[w.channel] = np.where(m, w.stuck_value, out[w.channel])
                elif w.kind == "SENSOR_SPIKE":
                    ch = w.channel or "vibration"
                    spk = m & (r.random(n) < 0.15)
                    out[ch] = np.where(spk, out[ch] * 6 + 20, out[ch])
                elif w.kind == "SENSOR_DISCONNECT":
                    for c in CHANNELS:
                        out[c] = np.where(m, np.nan, out[c])
                elif w.kind == "SENSOR_DROPOUT":
                    for c in CHANNELS:
                        out[c] = np.where(m & (r.random(n) < 0.4), np.nan, out[c])
            if cfg.p_missing > 0:
                for c in CHANNELS:
                    out[c] = np.where(r.random(n) < cfg.p_missing, np.nan, out[c])
        if not return_truth:
            return out
        seg_kind = np.array([s.kind for s in st.segs], dtype=object)[idx]
        seg_cid = np.array([s.cycle_id or "" for s in st.segs], dtype=object)[idx]
        truth = {
            "mode": cur, "state_letter": np.array([MODE_LETTER[Mode(int(m))] for m in cur], dtype=object),
            "cycle_id": seg_cid, "cycle_kind": seg_kind,
            "anomaly_kind": anom_kind, "sensor_fault": sensor_kind,
            "degradation": deg_name, "degradation_level": deg_level,
            "failure_epoch": fail_t,
        }
        return out, truth

    # ------------------------------------------------------------------- live
    @property
    def step_seconds(self) -> float:
        return self.cfg.interval_s * self.speed

    def generate_sensor_reading(self, station_id: str | None = None) -> list[dict]:
        """Generate one reading per station (or for one station) at the current simulated time."""
        t = np.array([self.now])
        res = []
        for st in self.stations:
            if station_id and st.station_id != station_id:
                continue
            out = self._render(st, t)
            rec = {"station_id": st.station_id, "timestamp": from_epoch(self.now)}
            for c in CHANNELS:
                v = float(out[c][0])
                rec[c] = None if math.isnan(v) else v
            res.append(rec)
        return res

    def step(self) -> list[dict]:
        readings = self.generate_sensor_reading()
        self.now += self.step_seconds
        self.tick += 1
        return readings

    def start_simulation(self):
        self.running = True

    def stop_simulation(self):
        self.running = False

    def reset_simulation(self, **kw):
        self.running = False
        self.reset(**kw)

    def get_simulation_status(self) -> dict:
        return {
            "running": self.running, "speed": self.speed, "tick": self.tick,
            "simulated_time": from_epoch(self.now).isoformat(), "seed": self.cfg.seed,
            "step_seconds": self.step_seconds, "conveyor_id": self.cfg.conveyor_id,
            "length_m": self.cfg.length_m, "n_stations": self.cfg.n_stations,
            "station_modes": {s.station_id: self.current_mode(s).name for s in self.stations},
        }

    # ------------------------------------------------------------- historical
    def generate_historical_dataset(self, start: datetime | None = None, days: float = 7, dt: float = 60.0,
                                    degradation_plan: list[dict] | None = None,
                                    anomaly_plan: list[dict] | None = None,
                                    stations: list[str] | None = None):
        """Return (features_df, truth_df). Truth columns are never needed at inference time.

        Features: timestamp, station_id + sensor channels. Truth: same keys + labels.
        """
        s0 = to_epoch(start) if start else self.t0
        times = np.arange(s0, s0 + days * DAY, dt)
        for p in degradation_plan or []:
            self.inject_degradation(p["station_id"], p["scenario"], p["duration_h"], start=p["start"], shape=p.get("shape", 1.5))
        for p in anomaly_plan or []:
            self.inject_anomaly(p["station_id"], p["kind"], p.get("duration_s", 1800), p.get("channel"), start=p["start"])
        feats, truths = [], []
        for st in self.stations:
            if stations and st.station_id not in stations:
                continue
            rng = np.random.default_rng([self.cfg.seed, 5, st.idx, int(s0)])
            out, tr = self._render(st, times, rng=rng, return_truth=True)
            ts = pd.to_datetime(times, unit="s", utc=True)
            f = pd.DataFrame({"timestamp": ts, "station_id": st.station_id, **out})
            t = pd.DataFrame({"timestamp": ts, "station_id": st.station_id, **tr})
            t["time_to_failure_h"] = (t["failure_epoch"] - times) / 3600.0
            truths.append(t)
            feats.append(f)
        return pd.concat(feats, ignore_index=True), pd.concat(truths, ignore_index=True)

    def ground_truth_cycles(self, until: float | None = None) -> pd.DataFrame:
        """Ground-truth duty cycles (from the schedule) for evaluation."""
        rows = []
        for st in self.stations:
            by = {}
            for s in st.segs:
                if s.cycle_id:
                    d = by.setdefault(s.cycle_id, {"station_id": st.station_id, "cycle_id": s.cycle_id,
                                                    "start": s.t0, "end": s.t1, "kind": s.kind})
                    d["start"] = min(d["start"], s.t0); d["end"] = max(d["end"], s.t1)
                    if s.kind != "NORMAL":
                        d["kind"] = s.kind
            rows += list(by.values())
        df = pd.DataFrame(rows)
        if df.empty:
            return df
        df["abnormal"] = df["kind"] != "NORMAL"
        df["start"] = pd.to_datetime(df["start"], unit="s", utc=True)
        df["end"] = pd.to_datetime(df["end"], unit="s", utc=True)
        return df.sort_values(["station_id", "start"]).reset_index(drop=True)
