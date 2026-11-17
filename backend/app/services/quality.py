"""Data-quality validation of incoming readings (Module 9). A sensor problem is NOT an equipment problem."""
from __future__ import annotations

import math
from collections import deque
from datetime import datetime

RANGES = {  # physically plausible ranges (prototype assumptions)
    "motor_rpm": (0, 120), "hydraulic_high_pressure": (0, 250), "hydraulic_low_pressure": (0, 80),
    "vibration": (0, 40), "temperature": (-30, 200), "motor_current": (0, 600),
    "material_load": (0, 2500), "belt_speed": (0, 12),
}
STUCK_N = 12          # identical consecutive values on a noisy analogue channel => stuck
SPIKE_JUMP = {"vibration": 8.0, "temperature": 40.0, "motor_current": 250.0}
CHANNELS = list(RANGES)


class QualityValidator:
    """Stateful per-station validator. Returns (status, detail) per reading."""

    def __init__(self):
        self.hist: dict[str, dict[str, deque]] = {}
        self.last_ts: dict[str, datetime] = {}

    def validate(self, station_id: str, ts: datetime, values: dict) -> tuple[str, str | None]:
        h = self.hist.setdefault(station_id, {c: deque(maxlen=STUCK_N - 1) for c in CHANNELS})
        last = self.last_ts.get(station_id)
        if last is not None and ts <= last:
            return "BAD_TIMESTAMP", f"timestamp {ts.isoformat()} not after previous {last.isoformat()}"
        self.last_ts[station_id] = ts
        missing = [c for c in CHANNELS if values.get(c) is None or (isinstance(values.get(c), float) and math.isnan(values[c]))]
        if len(missing) == len(CHANNELS):
            return "DISCONNECTED", "all channels missing"
        if missing:
            return "MISSING", "missing: " + ",".join(missing)
        for c in CHANNELS:
            lo, hi = RANGES[c]
            if not (lo <= values[c] <= hi):
                return "OUT_OF_RANGE", f"{c}={values[c]:.2f} outside [{lo},{hi}]"
        for c, jump in SPIKE_JUMP.items():
            if h[c] and abs(values[c] - h[c][-1]) > jump:
                d = abs(values[c] - h[c][-1])
                for k in CHANNELS:
                    h[k].append(values[k])
                return "SPIKE", f"{c} jumped by {d:.1f}"
        status, detail = "OK", None
        for c in ("vibration", "temperature", "motor_current"):   # noisy channels never repeat exactly
            dq = h[c]
            if len(dq) == STUCK_N - 1 and len(set(dq)) == 1 and values[c] == dq[-1]:
                status, detail = "STUCK", f"{c} constant for {STUCK_N} readings"
        for c in CHANNELS:
            h[c].append(values[c])
        return status, detail


def sensor_health(statuses: list[str], newest_age_s: float | None, expected_step_s: float) -> str:
    """ONLINE / DEGRADED / OFFLINE from the recent quality history and staleness."""
    if not statuses or newest_age_s is None:
        return "UNKNOWN"
    if newest_age_s > max(10 * expected_step_s, 600):
        return "OFFLINE"
    bad = sum(1 for s in statuses if s != "OK")
    if all(s in ("DISCONNECTED",) for s in statuses[-5:]):
        return "OFFLINE"
    frac = bad / len(statuses)
    return "OFFLINE" if frac > 0.8 else "DEGRADED" if frac > 0.1 else "ONLINE"
