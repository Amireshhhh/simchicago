# SimChicago v0.1

A scientifically grounded, individual-level simulation of daily life in Chicago, with a 3D viewer.
2,000 synthetic residents are calibrated to every community area's ACS statistics, choose
workplaces and commute modes with models fitted to LEHD and ACS data, plan their days jointly with
their households, and react (under an explicitly hypothesised mechanism) to real recorded
carjackings replayed from Chicago Police Department records.

Start with `docs/DESIGN.md` (mathematics, proofs, results), `docs/DATASETS.md`,
`docs/PARAMETERS.md` (generated provenance registry) and `docs/EVALUATION.md`.

## Install

```bash
python -m pip install -e ".[test]"          # Python 3.11+
cd viewer && npm install && npm run build && cd ..
```

## Run

```bash
python -m simchi.cli demo        # population, models, 4 runs of 5-11 Oct 2020, viewer export (~25 s)
python -m simchi.cli serve       # http://127.0.0.1:8000  (viewer at /, API docs at /docs)
python -m simchi.cli validate    # all validations -> reports/validation.json (~8 min)
python -m pytest tests           # 24 tests
cd viewer && npm test            # 8 tests
```

Single runs: `python -m simchi.cli run --incidents both --seed 2 --days 7 --name myrun`.
Scenario over HTTP: `POST /scenarios {"name": "calm", "incident_mode": "replay", "safety_overrides": {"a": 0.05}}`.

## Data

Pinned mirrors in `data/raw/mirror/` (sha256 in `data/sources.toml`) let everything run offline.
To pull official data on a normal connection:

```bash
python -m simchi.data.fetch crimes --start 2019-01-01 --end 2020-01-01
python -m simchi.data.fetch community_areas
python -m simchi.data.fetch buildings --bbox -87.64,41.875,-87.62,41.89
```

## Provenance in one paragraph

Agents are synthetic; no real person is represented. Incidents are labelled `observed` (CPD
records) or `simulated` (model draws) everywhere: event logs, API and viewer. Every agent variable
and model parameter carries one of six provenance classes (observed, estimated, fitted, latent,
scenario, hypothesis). The default buildings in the viewer are procedural; real footprints load
on request from the City of Chicago portal.
