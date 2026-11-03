import numpy as np
import pytest
from fastapi.testclient import TestClient

from simchi.api.app import RUNS, app
from simchi.pipeline import run
from simchi.sim.engine import SimConfig


@pytest.fixture(scope="module")
def client(built):
    run(built, SimConfig(n_days=1, seed=9, incident_mode="replay"), RUNS / "pytest_api")
    return TestClient(app)


def test_health_and_runs(client):
    assert client.get("/health").json() == {"ok": True}
    assert "pytest_api" in client.get("/runs").json()


def test_agent_and_positions(client):
    a = client.get("/runs/pytest_api/agents/0").json()
    assert a["label"] == "simulated" and a["segments"]
    seg = [s for s in a["segments"] if s["kind"] == "home"][0]
    p = client.get("/runs/pytest_api/positions", params={"t": seg["t0"] + 1e-3}).json()
    assert np.allclose(p["xy"][0], [seg["x0"], seg["y0"]], atol=0.1)


def test_rejects_bad_run_id(client):
    assert client.get("/runs/..%2Fetc/daily").status_code in (400, 404)
