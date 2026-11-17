from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from app.schemas import ResetRequest, ScenarioRequest, SpeedRequest
from app.simulator.engine import CYCLE_ANOMALY_KINDS, DEGRADATION, SENSOR_FAULT_KINDS, VALUE_ANOMALY_KINDS
from .deps import get_pipeline

router = APIRouter(prefix="/api/simulation", tags=["simulation"])


@router.get("/status")
def status(p=Depends(get_pipeline)):
    s = p.sim.get_simulation_status()
    s["belt"] = p.tracker.state()
    return s


@router.post("/start")
def start(p=Depends(get_pipeline)):
    p.sim.start_simulation()
    return status(p)


@router.post("/stop")
def stop(p=Depends(get_pipeline)):
    p.sim.stop_simulation()
    return status(p)


@router.post("/reset")
def reset(body: ResetRequest | None = None, p=Depends(get_pipeline)):
    body = body or ResetRequest()
    with p.lock:
        if body.seed is not None:
            p.sim.cfg = p.sim.cfg.with_(seed=body.seed)
        p.setup(warm_hours=body.warm_start_hours, demo_scenarios=body.demo_scenarios)
    return status(p)


@router.post("/speed")
def speed(body: SpeedRequest, p=Depends(get_pipeline)):
    p.sim.speed = body.speed
    return status(p)


@router.post("/step")
def step(n: int = 1, p=Depends(get_pipeline)):
    """Advance the simulation manually (used by tests/demos)."""
    if not 1 <= n <= 500:
        raise HTTPException(422, "n must be 1..500")
    r = None
    for _ in range(n):
        r = p.tick()
    return r


@router.get("/scenarios")
def scenarios():
    return {"anomalies": {"cycle_structure": CYCLE_ANOMALY_KINDS, "value_level": VALUE_ANOMALY_KINDS, "sensor_faults": SENSOR_FAULT_KINDS},
            "degradations": {k: {"component": v[0], "failure_type": v[1]} for k, v in DEGRADATION.items()}}


@router.post("/scenarios")
def inject(body: ScenarioRequest, p=Depends(get_pipeline)):
    with p.lock:
        try:
            if body.type == "anomaly":
                res = p.sim.inject_anomaly(body.station_id, body.kind, duration_s=body.duration, channel=body.channel)
            elif body.type == "degradation":
                res = p.sim.inject_degradation(body.station_id, body.kind, duration_h=body.duration)
            else:
                raise HTTPException(422, "type must be 'anomaly' or 'degradation'")
        except KeyError:
            raise HTTPException(404, f"station {body.station_id} not found")
        except ValueError as e:
            raise HTTPException(422, str(e))
    return {"injected": res}
