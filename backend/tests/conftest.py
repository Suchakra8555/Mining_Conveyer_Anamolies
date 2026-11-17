import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import pytest

from app.core.config import SimConfig


@pytest.fixture(scope="session")
def small_dataset():
    from datetime import datetime, timezone
    from app.simulator.engine import ConveyorSimulator
    start = datetime(2025, 1, 1, tzinfo=timezone.utc)
    sim = ConveyorSimulator(SimConfig(abnormal_cycle_prob=0.2, seed=7), start=start)
    feats, truth = sim.generate_historical_dataset(start, days=4)
    return sim, feats, truth


@pytest.fixture(scope="session")
def client(tmp_path_factory):
    os.environ["CONVEYOR_DB_URL"] = f"sqlite:///{tmp_path_factory.mktemp('db') / 't.db'}"
    os.environ["SIM_AUTOSTART"] = "false"
    from fastapi.testclient import TestClient
    from app.main import create_app
    with TestClient(create_app()) as c:
        yield c
