import numpy as np
import pandas as pd
import pytest

from simchi.experiments import Experiment, make_config, run_experiment
from simchi.sim.engine import SafetyParams, SimConfig, run_sim, safety_equilibrium


def test_make_config_applies_dotted_settings():
    cfg = make_config({"n_days": 2}, {"safety.a": 0.3, "mode_shift.transit": -1.0, "wfh_multiplier": 2}, seed=4)
    assert cfg.n_days == 2 and cfg.seed == 4 and cfg.safety.a == 0.3
    assert cfg.mode_shift["transit"] == -1.0 and cfg.wfh_multiplier == 2.0


def test_make_config_rejects_unknown_and_invalid_settings():
    with pytest.raises(KeyError):
        make_config({}, {"safety.not_a_parameter": 1}, seed=1)
    with pytest.raises(ValueError):
        make_config({}, {"safety.eta": 0.9, "safety.c": 0.5}, seed=1)      # eta + c > 1
    with pytest.raises(ValueError):
        make_config({}, {"incident_mode": "sometimes"}, seed=1)


def test_sweep_expands_into_scenarios():
    e = Experiment.from_dict({"name": "x", "replicates": 3, "sweep": [{"param": "safety.a", "values": [0, 0.5]}]})
    assert [s.name for s in e.scenarios] == ["safety.a = 0", "safety.a = 0.5"] and e.seeds == [1, 2, 3]


def test_equilibrium_is_a_fixed_point(built):
    p = SafetyParams()
    sbar = built.persons["sbar"].to_numpy()
    s = safety_equilibrium(sbar, built.network.W, p)
    s2 = (1 - p.eta - p.c) * s + p.eta * sbar + p.c * (built.network.W @ s)
    assert np.abs(s2 - s).max() < 1e-12
    assert sbar.min() - 1e-12 <= s.min() and s.max() <= sbar.max() + 1e-12


def test_no_incidents_means_no_cancellations(built):
    sim = run_sim(built, SimConfig(n_days=3, seed=3, incident_mode="none"))
    assert not [e for e in sim.events if e["kind"] == "cancelled"]
    assert np.allclose(sim.safety, sim.safety[:, :1])


def test_paired_effect_of_identical_scenarios_is_exactly_zero(built, tmp_path):
    e = Experiment.from_dict({"name": "same", "seeds": [1, 2], "base": {"n_days": 1},
                              "scenario": [{"name": "a"}, {"name": "b"}]})
    res = run_experiment(e, workers=1, outdir=tmp_path, built=built, progress=lambda m: None)
    eff = pd.DataFrame(res["effects"])
    assert (eff["diff"] == 0).all()
    assert (tmp_path / "runs.csv").exists() and (tmp_path / "experiment.json").exists()


def test_more_working_from_home_means_fewer_work_trips(built):
    a = run_sim(built, make_config({"n_days": 1, "incident_mode": "none"}, {}, 1))
    b = run_sim(built, make_config({"n_days": 1, "incident_mode": "none"}, {"wfh_multiplier": 4.0}, 1))
    assert b.wfh.sum() > a.wfh.sum()
    assert b.daily[0]["participation"]["work"] < a.daily[0]["participation"]["work"]


def test_scalar_travel_time_matches_vectorised(built):
    tm = built.travel
    for mode in (1, 2, 3, 4):
        for d in (0.0, 0.7, 3.2, 18.5):
            assert abs(tm.minutes_scalar(d, mode) - float(tm.minutes(d, mode))) < 1e-9


def test_transit_trips_use_the_network_skim(built):
    from simchi.sim.engine import SimConfig, scenario_skim
    sk = scenario_skim(built, SimConfig())
    w = built.world
    a, b = w.areas.loc[1, ["x", "z"]], w.areas.loc[32, ["x", "z"]]       # Rogers Park -> Loop centroids
    g = built.area_grid
    assert g.area_at(*a) == 1 and g.area_at(*b) == 32
    from simchi.behavior.travel import TravelModel
    tm = TravelModel(transit_total=sk.total, grid=g)
    assert tm.trip_minutes(tuple(a), tuple(b), 15.0, 3) == float(sk.total[0, 31])
