"""Build the synthetic city once, then run any number of simulations on it."""

from __future__ import annotations

import hashlib

from simchi import jsonutil
import pickle
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from simchi import __version__
from simchi.behavior.destination import GravityModel, fit_gravity
from simchi.behavior.mode_choice import ModeModel
from simchi.behavior.travel import AreaGrid, TravelModel, area_grid, fit_mode_and_travel
from simchi.data.cds import load_cds
from simchi.incidents.data import load_carjackings_2020
from simchi.incidents.intensity import IntensityModel, fit_intensity
from simchi.paths import DATA, ROOT, RUNS
from simchi.sim.engine import SimConfig, SimResult, run_sim
from simchi.social.network import Network, build_network
from simchi.synth.enrich import enrich
from simchi.synth.population import Population, synthesize
from simchi.world import OUTSIDE, World, build_world

# The intensity model is trained on data before the default simulated week (5-11 Oct 2020).
INTENSITY_TRAIN = ("2020-01-01", "2020-10-01")
# Discretionary destinations (hypothesis): P(j | i) ~ jobs_j^0.5 * households_j^0.5 * exp(-0.35 d_ij)
DISC_DECAY_PER_KM = 0.35


@dataclass
class Built:
    n: int
    seed: int
    world: World
    population: Population
    persons: pd.DataFrame
    gravity: GravityModel
    mode_model: ModeModel
    travel: TravelModel
    intensity: IntensityModel
    network: Network
    observed_incidents: pd.DataFrame
    disc_cum: np.ndarray
    disc_points: list
    skim: object = None                 # AM-peak CTA transit skim (simchi.transit.network.Skim)
    area_grid: AreaGrid | None = None
    fit_iterations: int = 0

    def fitted(self) -> dict:
        return {"gravity": self.gravity.as_dict(), "mode_choice": self.mode_model.as_dict(),
                "travel": self.travel.as_dict(), "intensity": self.intensity.as_dict()}


def _code_hash() -> str:
    h = hashlib.sha256(__version__.encode())
    for p in sorted((ROOT / "simchi").rglob("*.py")):
        h.update(p.read_bytes())
    h.update((DATA / "sources.toml").read_bytes())
    for name in ("meta.json", "patterns.json", "stops.json"):
        h.update((DATA / "transit" / name).read_bytes())
    return h.hexdigest()[:16]


def _discretionary(world: World):
    t = world.cds.table
    attr = 0.5 * np.log(world.areas["jobs"].to_numpy(float)) + 0.5 * np.log(t["TOT_HH"].to_numpy(float))
    V = attr[None, :] - DISC_DECAY_PER_KM * world.dist_km[:, :OUTSIDE]
    Pd = np.exp(V - V.max(1, keepdims=True))
    Pd /= Pd.sum(1, keepdims=True)
    return np.cumsum(Pd, 1)


def build(n: int = 2000, seed: int = 1, cache: bool = True) -> Built:
    path = RUNS / ".cache" / f"built_n{n}_s{seed}_{_code_hash()}.pkl"
    if cache and path.exists():
        with open(path, "rb") as f:
            return pickle.load(f)
    rng = np.random.default_rng(seed)
    world = build_world()
    pop = synthesize(load_cds(), n, seed=seed)
    gravity = fit_gravity(world)
    P_dest = gravity.probs(world)
    from simchi.transit.network import skim as transit_skim
    sk = transit_skim()
    mode_model, travel, iters = fit_mode_and_travel(world, P_dest, sk)
    incidents = load_carjackings_2020()
    intensity = fit_intensity(incidents, *INTENSITY_TRAIN)
    persons = enrich(pop, world, P_dest, rng)
    network = build_network(persons, rng)
    disc_points = [world.sample_points(a, 300, rng) for a in world.areas.index]
    built = Built(n=n, seed=seed, world=world, population=pop, persons=persons, gravity=gravity,
                  mode_model=mode_model, travel=travel, intensity=intensity, network=network,
                  observed_incidents=incidents, disc_cum=_discretionary(world), disc_points=disc_points,
                  skim=sk, area_grid=area_grid(world), fit_iterations=iters)
    if cache:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "wb") as f:
            pickle.dump(built, f)
    return built


def save_run(built: Built, sim: SimResult, outdir: Path):
    outdir = Path(outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(outdir / "segments.npz", **sim.segments)
    np.save(outdir / "safety.npy", sim.safety)
    incidents = pd.concat(sim.incidents, ignore_index=True) if sim.incidents else pd.DataFrame()
    incidents.to_csv(outdir / "incidents.csv", index=False)
    pd.DataFrame(sim.events).to_csv(outdir / "events.csv", index=False)
    with open(outdir / "run.json", "w") as f:
        jsonutil.dump({"version": __version__, "n_persons": len(built.persons), "build_seed": built.seed,
                   "config": sim.cfg.to_dict(), "daily": sim.daily, "fitted": built.fitted()}, f, indent=1)


def run(built: Built, cfg: SimConfig | None = None, outdir: Path | str | None = None) -> SimResult:
    sim = run_sim(built, cfg or SimConfig())
    if outdir is not None:
        save_run(built, sim, Path(outdir))
    return sim
