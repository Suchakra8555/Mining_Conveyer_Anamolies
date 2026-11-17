"""Centralised configuration (env-overridable). All simulation values are prototype assumptions."""
from __future__ import annotations

import os
from dataclasses import dataclass, field, replace
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
MODELS_DIR = REPO_ROOT / "models"
DATA_DIR = REPO_ROOT / "data"


def _env(name: str, default: str) -> str:
    return os.environ.get(name, default)


@dataclass(frozen=True)
class SimConfig:
    conveyor_id: str = "CV-001"
    length_m: float = 5000.0
    n_stations: int = 10
    nominal_rpm: float = 45.0
    nominal_belt_speed_ms: float = 4.0
    operating_hours: float = 18.0
    window_start_hour: float = 4.0          # operating window starts 04:00 (UTC) each day
    interval_s: float = 2.0                  # real-time tick interval for live mode
    seed: int = 42
    abnormal_cycle_prob: float = 0.0         # probability a generated cycle is abnormal
    p_missing: float = 0.002                 # per-channel random missing probability
    noise_scale: float = 1.0
    cycle_speed_threshold_rpm: float = 2.5   # duty-cycle detection threshold (calibrated to simulator idle noise)

    def with_(self, **kw) -> "SimConfig":
        return replace(self, **kw)


@dataclass(frozen=True)
class Settings:
    db_url: str = field(default_factory=lambda: _env("CONVEYOR_DB_URL", f"sqlite:///{REPO_ROOT / 'conveyor.db'}"))
    autostart: bool = field(default_factory=lambda: _env("SIM_AUTOSTART", "true").lower() == "true")
    warm_start_hours: float = field(default_factory=lambda: float(_env("SIM_WARM_START_HOURS", "12")))
    sim_speed: float = field(default_factory=lambda: float(_env("SIM_SPEED", "30")))
    inference_every_n_ticks: int = 5
    vision_weights: Path = field(default_factory=lambda: REPO_ROOT / _env("VISION_WEIGHTS", "models/vision/conveyor_defect.pt"))
    sim: SimConfig = field(default_factory=lambda: SimConfig(seed=int(_env("SIM_SEED", "42"))))


def get_settings() -> Settings:
    return Settings()
