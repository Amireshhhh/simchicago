# SimChicago v0.2

An individual-level, data-calibrated simulation of daily life in Chicago, an experiment
runner for running many scenarios across the whole city, and a 3D viewer.

- **2,000 synthetic residents** (configurable) calibrated exactly to every community area's
  ACS household and person statistics, placed in census tracts by population.
- **Commute destinations, modes and speeds** fitted to LEHD and ACS data; mode choice uses
  the real CTA network (walk, wait, in-vehicle time, transfers and fare of each area pair's
  AM-peak path from CTA's GTFS schedule), so service changes move riders; daily activity
  plans with work, school, aftercare and discretionary trips.
- **Real recorded carjackings** (CPD, 2020) replayed at their time and place, and/or drawn
  from an intensity model fitted to earlier months, with an explicitly *hypothesised*
  perceived-safety response spreading through a social network.
- **Experiments**: scenarios × replicates on one city, run in parallel with common random
  numbers and reported as paired effects with 95% intervals.
- **3D viewer**: physical sky and sun for the simulated time, Chicago's street grid lit at
  night, procedural skyline with lit windows, glowing residents with motion trails, commute
  flows, incident pulses, data lenses and an Experiment Lab.

- **Live CTA layer**: the real CTA network from CTA's GTFS feed (rail lines in their colours,
  bus routes, stations) and near-live bus and train positions, polled server-side in GitHub
  Actions within a documented request budget and published as static snapshots.

> **Transit data provided by Chicago Transit Authority** (GTFS, CTA Bus Tracker, CTA Train
> Tracker). SimChicago is **not affiliated with or endorsed by CTA**. Live positions are
> near-live snapshots (GitHub runs the workflow at most every 5 minutes, and runs can be
> delayed or skipped); they may be missing, delayed or wrong. Terms, limits and the request
> budget: `docs/CTA_TERMS.md`.

> **City of Chicago data portal** (community areas, CPD incident records, CTA ridership): “This site provides applications using data that has been modified for use from its original source, www.cityofchicago.org, the official website of the City of Chicago.  The City of Chicago makes no claims as to the content, accuracy, timeliness, or completeness of any of the data provided at this site.  The data provided at this site is subject to change at any time.  It is understood that the data provided at this site is being used at one’s own risk.”

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
python -m simchi.cli validate    # all validation checks -> reports/validation.json (~8 min)
python -m simchi.eval.ridership --replicates   # ridership validation -> reports/ridership_validation.json
python -m pytest tests           # 143 tests
cd viewer && npm test            # 14 tests
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
`n_days`, `start_date`, and the CTA network: `network.ivt_multiplier.bus` / `.rail` / `.<route
id>` (in-vehicle time), `network.headway_multiplier.…` (frequency), `network.wait_multiplier.…`
(waits, e.g. reliability), `network.fare_bus`,
`network.fare_rail`. Network settings change the transit skim, hence mode choice and transit
trip times (each new network scenario adds about 17 s, cached on disk). On 4 cores a week-long run of the default 2,000-agent city takes
about 0.6 s, so an experiment of 50 runs takes about 8 s; with `--agents 20000` the build
takes about 25 s and a week-long run about 7 s.

Over HTTP: `POST /scenarios {"name": "calm", "incident_mode": "replay", "safety_overrides": {"a": 0.05}}`
runs one scenario; `POST /experiments {"spec": {...}}` queues an experiment (same shape as the
TOML), and `GET /experiments/<name>` returns its results.

## Viewer

`npm run build` writes `viewer/dist/`; `python -m simchi.cli demo` writes its data
(`run.json`, `transit.json`, `insights.json`). The viewer has four modes, switched in the top
bar (or by URL: `#overview`, `#live`, `#insights`, `#simulate`):

- **Overview**: what SimChicago does, each claim with its real number and its source (observed,
  scheduled, simulated), over a slowly orbiting 3D city; only results with a passed test.
- **Live**: the real CTA network (rail lines in their colours with travelling light pulses, bus
  routes, stations) and the latest near-live snapshot: buses and trains reporting, trains by
  line, snapshot age, holding advice and feed flags, and the bus reliability lens. The sun and
  sky follow Chicago's current time.
- **Map**: a light, Google-Maps-like 2D map (MapLibre GL, open source) drawn from City of
  Chicago street centerlines, community areas and the CTA network, with near-live buses and
  trains, the simulated residents and optional layers. No third-party tiles or keys, and the 3D
  renderer is paused while it is open, so it runs on ordinary laptops and phones. Every bus and
  train in the latest snapshot moves along its route shape: the ~4 observed minutes are played
  back on a loop at 1×, 4× or 10× speed, several minutes behind real time (the delay is shown).
  Pick which 'L' lines and bus routes to show, click any vehicle to follow it (up to 10), and
  optionally show only the followed ones. Each vehicle is an icon (bus or train pictogram in its
  line colour; from zoom 13 a badge with the route or line and a direction arrow).
- **Where's my bus?** (Map tab): pick a route or line and your stop. It lists the vehicles heading
  to that stop, nearest first: distance along the route (GTFS stop pattern and shape), CTA's
  scheduled running time from there in the current timetable band (a schedule, not a
  prediction), and how long ago CTA reported the position. One click follows a vehicle.
- **Data**: the City of Chicago data portal catalog with measured freshness (fresh, late,
  overdue against each dataset's declared schedule), search, and access snippets.
- **Insights**: a dashboard of real data and validated results: CTA ridership 2024-2026,
  busiest routes and stations, every validation check with pass/fail, held-out ridership
  accuracy, the intervention ranking with 95% intervals and equity, crowding forecasts,
  anomaly detection and polling bias. Charts have hover tooltips.
- **Simulate**: the synthetic city's week (residents, trips, incidents), lenses, layers, the
  Experiment Lab and alternate timelines. Drag to pan, right-drag to rotate, scroll to zoom;
  Space plays, arrow keys step; click a resident or an area to inspect it.

## Live CTA layer

- `simchi/transit/gtfs.py` builds `data/transit/` (a derived extract of CTA's GTFS feed:
  routes, stations, simplified shapes, representative stop patterns, scheduled trips and
  headways per route, direction, day type and hour) in the simulation's coordinate frame.
  Refresh: `python scripts/fetch_gtfs.py --refresh` (see `docs/DATASETS.md`).
- `.github/workflows/live.yml` runs about every 5 minutes (each run queues the next, at most one per 5 minutes; an hourly schedule restarts the chain): `python -m simchi.transit.live` takes
  5 polls, 60 s apart (Bus Tracker `getvehicles`, 10 routes per request, only routes with
  scheduled service in the current hour; Train Tracker `ttpositions`), stops at a hard
  per-run request cap, writes `latest.json` (labelled `observed`) and redeploys the site.
  Each run's vehicle history is kept for 14 days as the workflow artifact `vehicles-<run id>`;
  nothing from polling is committed to git.
- The keys come only from the `CTA_BUS_KEY` and `CTA_TRAIN_KEY` Actions secrets; the browser
  never calls CTA. `tests/test_no_secrets.py` fails the deploy if anything key-like is in the
  site or the snapshot.
- In the viewer, **Live** and **Map** play back the ~4 observed minutes along route shapes
  (real speed by default, 4× or 10× on request), say how far behind real time the playback is,
  and show the snapshot age (older than 30 minutes: marked stale and not animated).
- Positions outside the CTA service area (Train Tracker has reported trains at lat 0, lon 0)
  are dropped and counted in the snapshot's notes; the snapshot is written as strict JSON, and
  `tests/test_published_json.py` blocks a deploy whose JSON a browser could not parse. This is
  delayed playback of server-side snapshots, not real-time tracking: the browser never calls CTA,
  and GitHub's schedule allows a new snapshot about every 5 minutes at best.

## Reliability (scheduled vs observed)

`python -m simchi.transit.reliability <dir of vehicles-* artifacts>` measures service delivered,
bunching, gaps, headway regularity and CTA-flagged delays per route and hour from the polled
positions against the GTFS schedule (`reports/reliability/`); the viewer's **Layers → Bus
reliability** colours bus routes by one of them once data are published. A simulated study
quantifies what 5-minute polling can recover (gaps undercounted, bunching slightly overcounted;
`docs/EVALUATION.md`). No observed reliability numbers exist yet: the polling workflow had not
run when this was written.

## Polling archive (durable history)

`.github/workflows/archive.yml` keeps an append-only history of the polling as GitHub release
assets (`history-<YYYY>`, outside git and outside the 14-day artifact retention): daily
aggregated statistics and segment run times; raw positions only if the repository variable
`ARCHIVE_RAW` is `on`. `python -m simchi.transit.archive aggregate` computes delivered vs
scheduled vehicles, headway CV, bunching and gaps (lower bounds) per route, direction, day type
and hour over the whole archive, and the Frequent Network delivered check, once the archive
reaches its pre-registered minimum (8 weeks). Other polling sources can be added in the same
ingestion schema (docstring of `simchi/transit/archive.py`); rider feedback is compared with
`python -m simchi.transit.feedback`. Seconds saved per skipped stop (W3) are estimated from the
archive once it spans 28 days (`python -m simchi.transit.stop_time`).

## Crash safety layer

`python -m simchi.safety.mirror` mirrors City of Chicago crash, Vision Zero, camera and traffic-count
data as aggregates (no person-level records); `python -m simchi.safety.crashes` snaps serious
crashes to street segments and intersections, fits a negative binomial model and ranks sites by
an empirical-Bayes estimate. The pre-registered test (top 100 sites' share of 2025 serious crashes
must beat raw counts and the 2024 counts) **fails**: 4.58% vs 4.64% (raw) and 3.66% (2024). Map tab
→ **Serious crashes**: severity by site, expressways grey (not CPD jurisdiction), a bus-corridor
filter, "crash concentration" where no traffic count exists, and source, age and method in each
tooltip. Camera before/after slice: no detectable change around 24 speed cameras.

## Promised vs delivered

`python -m simchi.commitments` computes the status of each commitment in `data/commitments.toml`
(CTA's Frequent Network standard; Vision Zero Chicago's goals) by fixed rules, never typed in;
Insights → **Promised vs delivered** shows them with the last-checked date and a corrections log.

## Internal / not validated

Simulated analyses without a passed, pre-registered test are kept (code and `reports/`) but are
not shown in the public modes: the intervention ranking, the fare scenarios, the response of
trips to service (and the safety-response experiments), and service design until W3 measures the
time saved per skipped stop. In the viewer they appear only after switching on **Insights →
Show internal analyses (not validated)**, each with a banner. The 3D renderer is frozen (fixes
only); new views go in the 2D map.

## Decision briefs

`python -m simchi.briefs` writes `docs/briefs/<finding>.md` (finding, evidence, what we don't
know, cost, and a pilot proposal with a success criterion fixed in advance) for each finding
whose test passed, reading every number from `reports/`. It refuses a brief whose test failed or
whose report is missing (`python -m simchi.briefs <finding>` exits non-zero then).

## Interventions (internal)

`python -m simchi.interventions --replicates 10` ranks eight CTA interventions (frequency,
bus priority, reliability, late-night service, fares) by simulated transit trips gained per
added scheduled vehicle-hour (or per $1,000 of fare revenue), with paired 95% intervals,
equity splits and job accessibility; results in `reports/interventions/`, summary in
`docs/BRIEF.md` (marked internal / not validated), chart in the viewer's Experiment Lab.

## Chicago open-data research layer

- `python -m simchi.portal.catalog --save` reads the City of Chicago data portal's catalog API
  (928 datasets on 18 Nov 2026) and measures each dataset's freshness against the update
  frequency the City declares for it (rules in the module docstring). The viewer's **Data** tab
  is a searchable board of it; `pages.yml` refreshes it on every build.
- `simchi.portal.client.Portal` fetches any dataset correctly: stable paging over any number of
  rows, columns converted to their declared types, retries with backoff, an on-disk cache keyed
  by the City's last-change time, and freshness next to every result.

```python
from simchi.portal.client import Portal
df = Portal().query("ijzp-q8t2", select="date, primary_type, community_area", where="date >= '2026-10-01'")
```

## Benches and seating

No public dataset of Chicago benches exists (the City portal has none). `python -m simchi.benches`
(run on every site build) combines OpenStreetMap benches, picnic tables, bus stops and platforms
with benches (Overpass API; © OpenStreetMap contributors, ODbL) with CTA's 2016 list of sheltered
stops, and estimates OpenStreetMap's completeness for shelters by capture-recapture (Chapman
estimator; method and assumptions in the module docstring). Map tab → "Benches & seating".

## Service design (internal until W3)

`python -m simchi.service_design --replicates 10` tests cost-saving service designs in the
simulation: re-allocating bus frequencies by the square-root rule (f ∝ √(ridership / round-trip
time), at 100%, 95% and 90% of today's bus-hours) and bus stop balancing on the ten busiest
routes. Results: `reports/service_design/`, the Insights page ("Service design") and
`docs/EVALUATION.md`.

## Operations tools

- `python -m simchi.ops.crowding`: one-week-ahead daily ridership per bus route and 'L' station
  and a crowding index (rides per scheduled trip); beats the same-day-last-week baseline on
  Jan-Aug 2026 (log error 0.134 vs 0.157 buses, 0.128 vs 0.151 stations).
- `python -m simchi.ops.holding`: a bunching/holding rule; it **failed** its pre-registered
  simulated test (passenger wait +2.6 min), so its advice is shown as advisory only.
- `python -m simchi.ops.anomalies`: rule-based live-feed anomaly flags, evaluated on constructed
  labels in a simulated feed only.
- `live.yml` writes `live/ops.json` (holding advice and flags for each snapshot), shown in the
  Live CTA panel.

## Results in one paragraph

Calibration is exact (largest deviation 1.9 × 10⁻⁹ over 77 areas); the destination model
beats its baseline in 8 of 9 held-out districts (a failure of its every-district criterion);
the network-based mode model beats city-wide shares in 9 of 9; held-out commute-time error is
3.51 min against 3.69 min for the city mean (lower overall, but in only 2 of 9 districts); the
incident model's spatial forecast beats population and uniform baselines on held-out months.
Ridership is validated on CTA's restated counts only (train 2025, test Jan-Aug 2026; CTA changed
its counting method on 2025-01-01): calibrated with scheduled service, the simulation's assigned
boardings improve held-out bus-route predictions (mean absolute log error 0.453 vs 0.473 for
scheduled service alone) and, narrowly, 'L' station entries (0.517 vs 0.522; not robust: 2 of 5
synthetic populations miss). Each unit's own 2025 ridership predicts 2026 far better (0.072 /
0.064). The earlier 2024-trained result is kept, labelled superseded (mixed counting methods).
Slowing CTA buses and trains 1.5× cuts simulated transit trips by 21% with no manual mode shift
(the time sensitivity is estimated cross-sectionally and probably overstated; see EVALUATION). Engine
invariants (day plans partition the day, safety stays in [0, 1], no response ≡ no incidents,
determinism) hold. Full numbers and limitations: `docs/EVALUATION.md`.

## Data

Pinned mirrors in `data/raw/mirror/` (sha256 in `data/sources.toml`) let everything run
offline: CMAP Community Data Snapshots by community area, CPD vehicular-hijacking records of
2020, 2014 tract indicators, and CTA daily ridership by bus route and 'L' station (2024 to
August 2026, City of Chicago data portal). Details in `docs/DATASETS.md`.

## Layout

```
simchi/
  data/        CDS loader and identity checks, tracts, projection
  synth/       raking, IPU, population synthesis, person attributes
  behavior/    destinations (gravity), mode choice, travel time, daily schedules
  transit/     CTA GTFS extract, network skim, live polling, shape interpolation
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
