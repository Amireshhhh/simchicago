"""W1 ridership evaluation: the held-out scoring and the persistence reference on constructed
data with known answers, and the guard against crossing CTA's 2025-01-01 method break."""

import numpy as np
import pandas as pd
import pytest

from simchi.eval import ridership as RV


def _units(n=40, seed=3):
    rng = np.random.default_rng(seed)
    ids = [f"r{i}" for i in range(n)]
    s = rng.uniform(50, 500, n)                                     # scheduled trips
    service = pd.Series(s, index=ids)
    model = pd.Series(np.zeros(n), index=ids)                       # model predicts nothing
    train = pd.Series(np.exp(1.0 + 1.0 * np.log(s)), index=ids)    # rides = e * trips exactly
    return train, model, service


def test_exact_service_relation_is_recovered_and_persistence_is_scored():
    train, model, service = _units()
    test = train * 1.1                                               # every unit grows 10%
    r = RV.evaluate(train, test, model, service)
    male = r["male_heldout_units_and_period"]
    # rides = e * trips holds exactly, so B_service fits it with error log(1.1) on every unit
    assert male["B_service"] == pytest.approx(np.log(1.1), abs=1e-9)
    # the model column is constant (log1p(0) = 0), so M_cal reduces to B_service
    assert male["M_cal"] == pytest.approx(male["B_service"], abs=1e-9)
    assert r["pass"] is False                                        # not strictly below B_service
    assert r["persistence_reference_male"] == pytest.approx(np.log(1.1), abs=1e-12)
    assert male["B_mean"] > male["B_service"]


def test_informative_model_passes():
    train, _, service = _units()
    rng = np.random.default_rng(7)
    noise = rng.normal(0, 0.3, len(train))
    truth = np.exp(1.0 + np.log(service.to_numpy()) + noise)
    train = pd.Series(truth, index=train.index)
    model = pd.Series(np.expm1(np.exp(noise)), index=train.index)   # log1p(model) = e^noise: monotone in the residual
    r = RV.evaluate(train, train * 1.05, model, service)
    assert r["male_heldout_units_and_period"]["M_cal"] < r["male_heldout_units_and_period"]["B_service"]
    assert r["pass"] is True


def test_periods_are_after_the_method_break():
    assert RV.METHOD_BREAK == "2025-01-01"
    assert RV.TRAIN == ("2025-01-01", "2025-12-31") and RV.TEST == ("2026-01-01", "2026-08-31")
    assert RV.TRAIN[0] >= RV.METHOD_BREAK and RV.TEST[0] > RV.TRAIN[1]
