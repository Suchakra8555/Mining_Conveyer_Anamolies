"""EXTENSION (not from the paper): simple rule-based residual checks for value-level operational anomalies.

Approach 2 only sees duty-cycle *structure*. Overload, hydraulic fluctuation, vibration, slippage and over-temperature
leave the cycle structure intact, so we flag them with transparent threshold rules on the latest running window.
Thresholds are calibrated to the simulator's normal ranges (vib<~2.6 mm/s, temp<~62 C, load<~950 t/h), NOT industrial specs.
"""
from __future__ import annotations

import pandas as pd

NOMINAL_RPM = 45.0
BELT_PER_RPM = 4.0 / 45.0

RULES = {
    "BELT_SLIPPAGE": ("MEDIUM", "belt speed deviates from motor speed"),
    "EXCESSIVE_VIBRATION": ("HIGH", "vibration above calibrated normal range"),
    "EXCESSIVE_TEMPERATURE": ("HIGH", "temperature above calibrated normal range"),
    "MOTOR_OVERLOAD": ("HIGH", "material load above calibrated range"),
    "HYDRAULIC_FLUCTUATION": ("MEDIUM", "high-pressure variance above calibrated range"),
}


def check_window(w: pd.DataFrame) -> list[dict]:
    """w: recent readings of ONE station (raw channels). Only running rows (rpm>10) are evaluated."""
    r = w[w["motor_rpm"] > 10]
    if len(r) < 5:
        return []
    out = []
    slip = 1 - (r["belt_speed"] / (r["motor_rpm"] * BELT_PER_RPM)).median()
    if slip > 0.08:
        out.append(("BELT_SLIPPAGE", f"slip={slip:.2f}", slip))
    vib = r["vibration"].median()
    if vib > 3.5:
        out.append(("EXCESSIVE_VIBRATION", f"vibration median={vib:.2f} mm/s", vib))
    temp = r["temperature"].median()
    if temp > 70:
        out.append(("EXCESSIVE_TEMPERATURE", f"temperature median={temp:.1f} C", temp))
    load = r["material_load"].median()
    if load > 1050:
        out.append(("MOTOR_OVERLOAD", f"material load median={load:.0f} t/h", load))
    hp = r["hydraulic_high_pressure"].diff().abs().median()
    if len(r) >= 8 and hp > 2.0:
        out.append(("HYDRAULIC_FLUCTUATION", f"|d high-pressure| median={hp:.1f} bar", hp))
    return [{"anomaly_type": k, "severity": RULES[k][0], "description": f"{RULES[k][1]} ({ev})", "value": float(v)} for k, ev, v in out]
