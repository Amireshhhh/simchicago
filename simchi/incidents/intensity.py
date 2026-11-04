"""Space-time intensity model for carjackings, fitted to recorded CPD incidents.

Daily count     N_d ~ Poisson(L * omega[weekday(d)])          mean(omega) = 1
Hour            h ~ Categorical(eta)                           sum(eta) = 1
Area            area counts in a period ~ DirMult(n, alpha * pi)   sum(pi) = 1

pi, eta and omega are smoothed frequencies over the training window (add-1/2), L is the
training mean per day, and the concentration alpha is the maximum-likelihood value for the
weekly area-count vectors: small alpha means the spatial pattern shifts from week to week
(overdispersion relative to a fixed multinomial), alpha -> infinity recovers the multinomial.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from scipy.optimize import minimize_scalar
from scipy.special import gammaln


def dm_loglik(alpha: float, counts: np.ndarray, m: np.ndarray) -> float:
    """Dirichlet-multinomial log-likelihood of the rows of `counts` (without the
    multinomial coefficient, which does not depend on the parameters)."""
    counts = np.asarray(counts, float)
    a = alpha * np.asarray(m, float)
    N = counts.sum(1)
    return float((gammaln(alpha) - gammaln(N + alpha)).sum() + (gammaln(counts + a) - gammaln(a)).sum())


@dataclass
class IntensityModel:
    level_per_day: float
    pi: np.ndarray        # (77,) area shares, index = area number - 1
    eta: np.ndarray       # (24,) hour-of-day shares
    omega: np.ndarray     # (7,) weekday multipliers (Mon=0), mean 1
    alpha: float          # Dirichlet-multinomial concentration of weekly area counts
    train: tuple

    def expected_per_day(self, date) -> float:
        return self.level_per_day * self.omega[pd.Timestamp(date).weekday()]

    def sample_day(self, date, rng: np.random.Generator, world, next_id: int = -1) -> pd.DataFrame:
        date = pd.Timestamp(date).normalize()
        n = rng.poisson(self.expected_per_day(date))
        if n == 0:
            return pd.DataFrame(columns=["record_id", "time", "t_min", "area", "x", "z", "label", "desc"])
        p = rng.dirichlet(self.alpha * self.pi)
        areas = rng.choice(len(p), size=n, p=p) + 1
        minutes = rng.choice(24, size=n, p=self.eta) * 60 + rng.uniform(0, 60, n)
        xy = np.vstack([world.sample_points(int(a), 1, rng) for a in areas])
        return pd.DataFrame({
            "record_id": np.arange(next_id, next_id - n, -1),
            "time": date + pd.to_timedelta(minutes, unit="min"),
            "t_min": minutes, "area": areas, "x": xy[:, 0], "z": xy[:, 1],
            "label": "simulated", "desc": "VEHICULAR HIJACKING (simulated)",
        }).sort_values("t_min").reset_index(drop=True)

    def as_dict(self):
        return {"level_per_day": self.level_per_day, "alpha": self.alpha,
                "train": [str(self.train[0]), str(self.train[1])]}


def weekly_area_counts(df: pd.DataFrame, start, end) -> np.ndarray:
    d = df[(df["time"] >= start) & (df["time"] < end)]
    week = ((d["time"] - pd.Timestamp(start)).dt.days // 7).to_numpy()
    n_weeks = (pd.Timestamp(end) - pd.Timestamp(start)).days // 7
    keep = week < n_weeks                      # only complete weeks
    out = np.zeros((n_weeks, 77))
    np.add.at(out, (week[keep], d["area"].to_numpy()[keep] - 1), 1)
    return out


def fit_intensity(df: pd.DataFrame, start, end) -> IntensityModel:
    start, end = pd.Timestamp(start), pd.Timestamp(end)
    d = df[(df["time"] >= start) & (df["time"] < end)]
    days = (end - start).days
    n = len(d)
    area_n = np.bincount(d["area"] - 1, minlength=77).astype(float)
    pi = (area_n + 0.5) / (n + 0.5 * 77)
    hour_n = np.bincount(d["time"].dt.hour, minlength=24).astype(float)
    eta = (hour_n + 0.5) / (n + 0.5 * 24)
    dow_n = np.bincount(d["time"].dt.day_of_week, minlength=7).astype(float)
    # Weekday frequencies relative to the number of each weekday in the window.
    n_dow = np.bincount(pd.date_range(start, end - pd.Timedelta(days=1)).day_of_week, minlength=7)
    rate = (dow_n + 0.5) / n_dow
    omega = rate / rate.mean()
    W = weekly_area_counts(df, start, end)
    res = minimize_scalar(lambda la: -dm_loglik(np.exp(la), W, pi), bounds=(np.log(1e-2), np.log(1e5)), method="bounded")
    return IntensityModel(level_per_day=n / days, pi=pi, eta=eta, omega=omega, alpha=float(np.exp(res.x)), train=(start, end))
