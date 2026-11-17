from datetime import datetime, timezone

import numpy as np
import pytest

from app.core.config import SimConfig
from app.simulator.engine import (ABNORMAL_TRANSITIONS, CHANNELS, ConveyorSimulator, Mode, is_valid_transition)

START = datetime(2025, 1, 1, tzinfo=timezone.utc)


def test_station_generation_and_positions():
    sim = ConveyorSimulator(SimConfig(), start=START)
    assert len(sim.stations) == 10
    assert [s.position_m for s in sim.stations] == [i * 500.0 for i in range(10)]
    assert sim.stations[3].station_id == "ST-004" and sim.stations[3].position_km == 1.5
    assert len({s.uuid for s in sim.stations}) == 10


def test_configurable_stations():
    sim = ConveyorSimulator(SimConfig(length_m=2000, n_stations=4), start=START)
    assert [s.position_m for s in sim.stations] == [0, 500, 1000, 1500]


def test_reproducible_for_same_seed():
    a = ConveyorSimulator(SimConfig(seed=1), start=START).generate_historical_dataset(START, days=1)[0]
    b = ConveyorSimulator(SimConfig(seed=1), start=START).generate_historical_dataset(START, days=1)[0]
    c = ConveyorSimulator(SimConfig(seed=2), start=START).generate_historical_dataset(START, days=1)[0]
    assert a.equals(b) and not a.equals(c)


def test_schema_and_ranges(small_dataset):
    _, f, _ = small_dataset
    assert set(CHANNELS) <= set(f.columns)
    assert f["motor_rpm"].max() < 60 and f["motor_rpm"].min() >= 0
    assert (f["hydraulic_high_pressure"].dropna() > f["hydraulic_low_pressure"].dropna().min()).any()


def test_missing_measurements_present(small_dataset):
    _, f, _ = small_dataset
    assert f[CHANNELS].isna().mean().max() > 0


def test_ground_truth_is_separate_from_features(small_dataset):
    _, f, t = small_dataset
    assert not ({"mode", "cycle_kind", "degradation", "failure_epoch"} & set(f.columns))
    assert {"mode", "state_letter", "cycle_kind", "degradation_level", "time_to_failure_h"} <= set(t.columns)
    assert len(f) == len(t)


def test_normal_cycles_follow_valid_transitions(small_dataset):
    sim, _, _ = small_dataset
    for st in sim.stations:
        for a, b in zip(st.segs, st.segs[1:]):
            if a.kind == "NORMAL" and b.kind == "NORMAL":
                assert is_valid_transition(a.mode, b.mode) or a.mode == b.mode, (a.mode, b.mode)


def test_abnormal_transitions_are_the_documented_set():
    assert not is_valid_transition(Mode.IDLE, Mode.ACTIVE)
    assert (Mode.IDLE, Mode.ACTIVE) in ABNORMAL_TRANSITIONS


def test_abnormal_cycle_kinds_generated(small_dataset):
    sim, _, _ = small_dataset
    kinds = set(sim.ground_truth_cycles()["kind"])
    assert {"NORMAL", "UNEXPECTED_STOP", "ABNORMAL_STARTUP", "INTERMITTENT_OPERATION"} <= kinds


def _day(sim, **kw):
    return sim.generate_historical_dataset(START.replace(hour=0), days=1, **kw)


def test_load_increases_current_and_pressure(small_dataset):
    _, f, t = small_dataset
    d = f.merge(t[["timestamp", "station_id", "mode"]], on=["timestamp", "station_id"])
    act = d[d["mode"] == int(Mode.ACTIVE)]
    idle = d[d["mode"] == int(Mode.IDLE)]
    assert act["motor_current"].mean() > 5 * idle["motor_current"].mean()
    assert act["hydraulic_high_pressure"].mean() > idle["hydraulic_high_pressure"].mean() + 30
    assert act[["material_load", "motor_current"]].corr().iloc[0, 1] > 0.5


def test_bearing_degradation_raises_vibration_and_temperature():
    base = ConveyorSimulator(SimConfig(seed=3, p_missing=0), start=START)
    deg = ConveyorSimulator(SimConfig(seed=3, p_missing=0), start=START)
    plan = [{"station_id": "ST-001", "scenario": "bearing_degradation", "duration_h": 20, "start": START.timestamp() + 4 * 3600}]
    fb, _ = base.generate_historical_dataset(START, days=1)
    fd, td = deg.generate_historical_dataset(START, days=1, degradation_plan=plan)
    m = (td.station_id == "ST-001") & (td.degradation_level > 0.7) & (td["mode"] == int(Mode.ACTIVE))
    b = fb[(fb.station_id == "ST-001")]
    d = fd[(fd.station_id == "ST-001")]
    assert m.any()
    idx = td.index[m]
    assert d.loc[idx, "vibration"].mean() > b.loc[idx, "vibration"].mean() + 2
    assert d.loc[idx, "temperature"].mean() > b.loc[idx, "temperature"].mean() + 8
    assert (td.loc[td.station_id == "ST-001", "failure_epoch"].dropna() == START.timestamp() + 24 * 3600).all()


def test_belt_slippage_diverges_speed():
    sim = ConveyorSimulator(SimConfig(seed=3, p_missing=0), start=START)
    sim.inject_anomaly("ST-002", "BELT_SLIPPAGE", duration_s=3600 * 20, start=START.timestamp())
    f, t = sim.generate_historical_dataset(START, days=1)
    s = f[(f.station_id == "ST-002") & (t.loc[f.index, "mode"] == int(Mode.ACTIVE))]
    ratio = s["belt_speed"] / (s["motor_rpm"] * 4 / 45)
    assert 0.80 < ratio.median() < 0.90


def test_live_step_advances_clock_and_returns_all_stations():
    sim = ConveyorSimulator(SimConfig(), start=START)
    t0 = sim.now
    r = sim.step()
    assert len(r) == 10 and sim.now == t0 + sim.step_seconds and sim.tick == 1
    sim.speed = 1
    assert sim.step_seconds == 2.0


def test_inject_validation():
    sim = ConveyorSimulator(SimConfig(), start=START)
    with pytest.raises(ValueError):
        sim.inject_anomaly("ST-001", "NOPE")
    with pytest.raises(ValueError):
        sim.inject_degradation("ST-001", "nope")
    with pytest.raises(KeyError):
        sim.inject_anomaly("ST-999", "BELT_SLIPPAGE")


def test_controls():
    sim = ConveyorSimulator(SimConfig(), start=START)
    sim.start_simulation(); assert sim.get_simulation_status()["running"]
    sim.stop_simulation(); assert not sim.get_simulation_status()["running"]
    sim.step(); sim.reset_simulation(); assert sim.tick == 0
