# SimChicago v0.2

An individual-level, data-calibrated simulation of daily life in Chicago, an experiment
runner for running many scenarios across the whole city, and a 3D viewer.

- **2,000 synthetic residents** (configurable) calibrated exactly to every community area's
  ACS household and person statistics, placed in census tracts by population.
- **Commute destinations, modes and speeds** fitted to LEHD and ACS data; daily activity
  plans with work, school, aftercare and discretionary trips.
- **Real recorded carjackings** (CPD, 2020) replayed at their time and place, and/or drawn
  from an intensity model fitted to earlier months, with an explicitly *hypothesised*
  perceived-safety response spreading through a social network.
- **Experiments**: scenarios × replicates on one city, run in parallel with common random
  numbers and reported as paired effects with 95% intervals.
- **3D viewer**: physical sky and sun for the simulated time, Chicago's street grid lit at
  night, procedural skyline with lit windows, glowing residents with motion trails, commute
  flows, incident pulses, data lenses and an Experiment Lab.

Agents are synthetic; no real person is represented. Every agent variable and parameter
carries a provenance class (observed, estimated, fitted, latent, scenario, hypothesis), and
incidents are labelled `observed` or `simulated` everywhere.

> **v0.2 is a rewrite.** The v0.1 backend and documents reached this repository zero-filled
> and could not be recovered. v0.2 rebuilds the backend to the surviving tests and README,
> keeps the v0.1 viewer's core, and adds the experiment runner, a new renderer and an
> out-of-sample validation suite. See `docs/DATASETS.md` for what was lost.

Start with `docs/DESIGN.md` (models, maths and proofs), `docs/EVALUATION.md` (validation
and experiment results, including the checks that fail), `docs/DATASETS.md` and
`docs/PARAMETERS.md` (every parameter with its value and provenance).

## Install

```bash
python -m pip install -e ".[test]"          # Python 3.11+
cd viewer && npm install && npm run build && cd ..
```

## Run

```bash
python -m simchi.cli demo        # build the city, the default week, comparison runs, 4 experiments, viewer data (< 1 min)
python -m simchi.cli serve       # http://127.0.0.1:8000  (viewer at /, API docs at /docs)
python -m simchi.cli validate    # all validation checks -> reports/validation.json (~1 min)
python -m pytest tests           # 31 tests
cd viewer && npm test            # 8 tests
```

The first command that needs the city builds it (about 25 s) and caches it in
`runs/.cache`; the cache is invalidated automatically when the code or data change.
Use `--agents 20000` (before the command) for a larger population.

Single runs:

```bash
python -m simchi.cli run --name myrun --incidents both --days 7 --seed 2 --set wfh_multiplier=2 --set safety.a=0.3 --export
```

## Experiments

An experiment is a TOML file. Four are included in `configs/experiments/`:
`incident_response`, `safety_sensitivity`, `remote_work`, `transit_disruption`.

```toml
name = "remote_work"
replicates = 10
baseline = "ACS work-from-home shares"
[build]
n = 2000
seed = 1
[base]
n_days = 7
incident_mode = "both"
[[scenario]]
name = "ACS work-from-home shares"
[[sweep]]
param = "wfh_multiplier"
label = "work-from-home x"
values = [0.5, 2.0, 4.0, 8.0]
```

```bash
python -m simchi.cli experiment configs/experiments/remote_work.toml --replicates 30
```

Results go to `reports/experiments/<name>/` (`runs.csv` per run, `summary.csv`, `effects.csv`,
`experiment.json`). Settings are dotted paths into the simulation config, e.g.
`safety.gamma_cancel`, `mode_shift.transit`, `time_multiplier.transit`,
`simulated_incident_multiplier`, `schedule.discretionary_multiplier`, `incident_mode`,
`n_days`, `start_date`. On 4 cores a week-long run of the default 2,000-agent city takes
about 0.6 s, so an experiment of 50 runs takes about 8 s; with `--agents 20000` the build
takes about 25 s and a week-long run about 7 s.

Over HTTP: `POST /scenarios {"name": "calm", "incident_mode": "replay", "safety_overrides": {"a": 0.05}}`
runs one scenario; `POST /experiments {"spec": {...}}` queues an experiment (same shape as the
TOML), and `GET /experiments/<name>` returns its results.

## Viewer

`npm run build` writes `viewer/dist/` (`index.html` + `app.js`, and a single-file
`standalone.html`); it reads `viewer/dist/data/run.json`, written by `demo` or `export`.
Controls: drag to pan, right-drag to rotate, scroll to zoom; Space plays, arrow keys step;
click a resident or an area to inspect it; **Experiment Lab** shows every exported
experiment; **Fly-through** tours the city; **Layers** toggles buildings, trails, commute
flows, labels, incidents and a what-if rain overlay. Buildings are procedural; **Load real
buildings here** fetches footprints around the camera from the City of Chicago data portal
(not testable offline; not exercised in this repository's tests).

## Results in one paragraph

Calibration is exact (largest deviation 1.9 × 10⁻⁹ over 77 areas); destination and mode
models beat simple baselines on held-out districts in 8 of 9 districts each; the incident
model's spatial forecast beats population and uniform baselines on held-out months; the
commute-time model has no skill beyond the city mean on held-out districts. Engine
invariants (day plans partition the day, safety stays in [0, 1], no response ≡ no incidents,
determinism) hold. Full numbers and limitations: `docs/EVALUATION.md`.

## Data

Pinned mirrors in `data/raw/mirror/` (sha256 in `data/sources.toml`) let everything run
offline: CMAP Community Data Snapshots by community area, CPD vehicular-hijacking records of
2020, and 2014 tract indicators. Details in `docs/DATASETS.md`.

## Layout

```
simchi/
  data/        CDS loader and identity checks, tracts, projection
  synth/       raking, IPU, population synthesis, person attributes
  behavior/    destinations (gravity), mode choice, travel time, daily schedules
  incidents/   CPD records, intensity model
  social/      network
  sim/         engine (exposure, safety dynamics, daily summaries)
  eval/        validation suite, incident forecast check
  export/      viewer data
  api/         FastAPI app
  experiments.py, pipeline.py, registry.py, cli.py
configs/experiments/   experiment definitions
viewer/                three.js viewer (src/, test/, build.mjs)
docs/                  DESIGN, EVALUATION, DATASETS, PARAMETERS
reports/               validation.json, experiments/
tests/                 pytest suite
```

## License

MIT, © 2026 Amirreza Eshraghi.
