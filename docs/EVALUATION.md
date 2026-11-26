# Evaluation

All numbers below come from `python -m simchi.cli validate` (→ `reports/validation.json`)
and the experiment runs in `reports/experiments/*/experiment.json`, on the default build:
2,000 requested agents (1,944 drawn, standing for 2,589,487 household residents), seed 1.

Every model check is **out of sample** and compares against a **simple baseline**, with the
pass criterion fixed before the results were seen. Three checks fail their criterion (commute
destinations; the simulated holding test; the W4 crash ranking); they are reported as failures, not re-defined. The
'L' ridership check failed under the superseded design (2024 vs 2025-26 counts, mixed counting
methods) and passes narrowly under the W1 re-baseline; both results are kept below. v0.3 workstream 2 replaced the
distance-based mode choice and travel times by CTA-network ones; the two checks that failed in
v0.2 (mode choice 8/9 districts, commute time 3.74 vs 3.69 min) were re-run under the same
criteria and now pass (numbers below).

## Validation

| Check | Result | Criterion | Outcome |
|---|---|---|---|
| Data integrity | 7/7 mirrors match their pinned sha256 | all match | **pass** |
| CDS count identities | 12 identities hold within 1.22% in every area; LEHD orientation bounds hold | < 1.5% and bounds hold | **pass** |
| Calibration | 77/77 areas, max relative deviation 1.9 × 10⁻⁹; household weights / TOT_HH = 1.000000; person weights / POP_HH = 0.9773 | < 10⁻⁶; exact; within 3% | **pass** |
| Commute destinations (gravity), leave one district out | held-out log-likelihood better than jobs-proportional destinations in 8 of 9 districts (worse in the Far Southwest Side); in-sample correlation of the 385 listed top-5 shares 0.919, mean absolute error 3.0 share points | better in every district | **fail** |
| Commute mode (network level of service), leave one district out | better than city-wide shares in 9 of 9 districts; in-sample area correlations car 0.88, transit 0.81, walk 0.85, other 0.32 | better in every district | **pass** (v0.2 distance model: 8/9, fail) |
| Commute time (network transit times), leave one district out | mean absolute error 3.51 min against 3.69 min for predicting the city mean; lower in only 2 of 9 districts; in-sample correlation 0.47 | lower error than the city mean | **pass** (v0.2: 3.74 min, fail) |
| CTA GTFS extract | built from the pinned feed; 132 routes (8 rail), 143 stations, 357 patterns covering on average 95.8% of each route-direction's weekday trips | matches pinned sha256 | **pass** |
| Incident forecast (train Jan-Sep 2020, test Oct-Dec) | weekly area counts (13 weeks, 508 incidents): log score −1976.1 (model) vs −2203.1 (population-proportional) and −2206.7 (uniform) | beat both baselines | **pass** |
| Ridership, bus routes (W1: train 2025, test Jan-Aug 2026, held-out routes; pre-registered ea4f406) | mean absolute log error 0.453 (simulation + scheduled service) vs 0.473 (scheduled service) and 1.007 (constant), 124 routes | below both baselines | **pass** |
| Ridership, 'L' stations (W1, same design) | 0.517 vs 0.522 (scheduled service) and 0.678 (constant), 123 stations; fails in 2 of 5 replicate populations | below both baselines | **pass** (not robust) |
| *Superseded: mixed counting methods* (train 2024 farebox method, test 2025-26 APC method) | bus 0.447 vs 0.476 (pass); 'L' 0.500 vs 0.496 (fail) | | superseded |
| Crowding forecast, bus routes (one week ahead, Jan-Aug 2026) | log error 0.1339 vs 0.1569 (same day last week), 27,946 forecasts | below the baseline | **pass** |
| Crowding forecast, 'L' stations | 0.1280 vs 0.1508, 34,992 forecasts | below the baseline | **pass** |
| Holding rule (simulated, pre-registered) | mean passenger wait +2.58 min [+1.57, +3.59]; after a later start-up fix −0.94 [−1.80, −0.09] | 95% interval below 0 | **fail** |
| Crash ranking (W4: empirical Bayes on 2018-2024, test 2025; pre-registered cb367e0) | top 100 sites hold 4.58% of 2025 serious crashes (70 of 1,530) vs 4.64% (71) raw 2018-2024 counts and 3.66% (56) 2024 counts | beat both | **fail** |
| Anomaly detectors (simulated feed, constructed labels) | precision / recall: jump 1.00 / 0.96, stuck 1.00 / 0.79, off route 0.98 / 0.78, outage 0.75 / 1.00 | none (reported) | info |
| Engine invariants (3-day run, 5,832 agent-days; 2-day CRN and repeat runs) | every day plan partitions [0, 1440]; safety stays in [0, 1]; no behavioural response ≡ no incidents; runs are deterministic | all hold | **pass** |

### What the results mean

- **Destinations** generalise to held-out districts almost everywhere, but not everywhere
  (worse than jobs-proportional in the 6-area Far Southwest Side). With five aggregate
  parameters, area-specific patterns are not captured.
- **Modes** now generalise to every held-out district. The model uses the CTA network
  (walk, wait and in-vehicle minutes, transfers and fare of the AM-peak path between areas)
  instead of straight-line distance and a survey-based transit-access index.
- **Commute time** passes its criterion, but narrowly and unevenly: the city-wide held-out
  error falls below the city mean's (3.51 vs 3.69 min) mainly because of the Far South Side
  (2.70 vs 7.25 min); the model is worse than the city mean in 7 of 9 districts, by up to
  3.4 min in the Northwest Side (6.26 vs 2.82). Per district (model / city mean, min):
  Central 8.09 / 7.54, Far North 2.07 / 2.06, Far South Side 2.70 / 7.25, Far Southwest
  Side 3.92 / 3.76, North Side 2.31 / 1.21, Northwest Side 6.26 / 2.82, South Side
  5.11 / 4.21, Southwest Side 1.97 / 2.03, West Side 3.45 / 3.30. The car side is still one
  fitted door-to-door speed (50.7 km/h; no road network or congestion). Treat area-level
  travel-time claims with caution.
- **Incident level.** The spatial forecast beats both baselines, but the level does not
  transfer: October-December 2020 averaged 5.57 carjackings per day against 3.28 fitted on
  January-September. Simulated incidents in the default week (5-11 Oct 2020) therefore
  understate the recorded rate; use `simulated_incident_multiplier` to explore higher levels.

### Mode choice: estimates and identification

From `reports/validation.json` and `python scripts/mode_identification.py`
(→ `reports/mode_choice_identification.json`). Fitted alternately with the car speed
(9 iterations to a change below 0.01 km/h):

| Coefficient | Constrained (used) | Free in [−15, 15] | Range over the 9 leave-one-district-out fits |
|---|---|---|---|
| in-vehicle time, per min | −0.143 | −0.176 | −0.155 to −0.125 |
| wait, per min | −0.147 | −0.328 | −0.191 to −0.109 |
| walk, per min (access/egress and walk mode) | −0.157 | −0.144 | −0.187 to −0.127 |
| transfer, per transfer | 0 (at bound) | +1.85 | 0 |
| transit, no vehicle | 4.86 | 11.9 | 3.93 to 5.18 |
| walk, no vehicle | 8 (at cap) | 15 (at bound) | 8 |
| fare, per dollar | −0.572 (from b_ivt and an assumed value of time of $15/h; not estimated) | | |

- **Constraints that bind**: the transfer coefficient (unconstrained it is positive, i.e.
  transfers would *attract* riders, which is not credible) and the walk no-vehicle effect.
  Removing all constraints raises the log-likelihood by 0.12% (−1,111,893 vs −1,113,203).
- **Identification**: the observed information of the per-commuter log-likelihood over the
  nine free coefficients has condition number 3.0 × 10⁵; the walk constant and the walk-time
  coefficient are correlated at −0.97, so they are not separately well identified. The ACS
  counts are not independent choices, so no standard errors are reported.
- **Not identified from these data**: the fare coefficient (fares are $2.25 or $2.50
  everywhere, so their effect is absorbed by the transit constant) and the transfer penalty.
- **Implied sensitivities** (city transit share, arc elasticity for +10%): in-vehicle time
  −1.60, wait −0.42; fare −0.80, −0.49, −0.26 at an assumed value of time of $10, $15, $25
  per hour. The time elasticity is estimated from cross-sectional differences between areas,
  which also differ in ways the model does not see (parking, density, income), so it is
  probably an upper bound on the causal response; scenario effects on ridership should be
  read with that in mind.
- Model city transit share 29.87% vs ACS 29.76%.

## Ridership (CTA bus routes and 'L' stations), W1 re-baseline

From `python -m simchi.eval.ridership --replicates` (→ `reports/ridership_validation.json`).
Design and pass criteria: docstring of `simchi/eval/ridership.py`, committed as ea4f406 ("W1
pre-registration") before this design was run.

**Why it was re-run.** CTA restated its ridership from 2025-01-01 (portal note "Changes to CTA
Ridership Datasets - 3/20/2026": automatic passenger counter factoring, recorded cash-farebox
counts, underpaid rail rides added at station level; bus 2025 total 184.0m → 199.6m). The earlier
design trained on 2024 (old method) and tested on 2025-26 (new method), so part of what it
measured was the method change. W1 trains on 2025 and tests on 2026, both after the break. The
mirrors equal the portal's post-restatement data (checked 2026-11-23; see `docs/DATASETS.md`).

**What has been seen before.** 2025-26 ridership was the test period of the superseded design and
its results were examined. Nothing in W1 was chosen from them: the units, folds, baselines,
predictors and criterion are the earlier ones; only the periods moved. So W1 is held out in units
(5 folds) and in time (2026 vs 2025), but the 2025-26 data are not unseen.

**Units**: 124 bus routes and 123 'L' stations inside the city with positive ridership in both
periods. Observed totals over the units: buses 618,318 → 625,643 rides per weekday, 'L'
330,527 → 347,439 entries. The model's commute demand (752,452 weekday transit trips) and
its features are unchanged.

| Predictor of log rides | Bus routes | 'L' stations |
|---|---|---|
| B_mean: constant | 1.007 | 0.678 |
| B_service: scheduled weekday trips (log-linear) | 0.473 | 0.522 |
| M_sim: simulation, one scale factor | 1.076 | 0.989 |
| **M_cal: simulation + scheduled trips (log-linear)** | **0.453** | **0.517** |
| Criterion: M_cal below both baselines | **pass** | **pass** |
| Persistence reference: each unit's own 2025 mean (not a criterion) | 0.072 | 0.064 |

- **Buses**: the simulation calibrated with scheduled service lowers the held-out error from
  0.473 to 0.453 (4%). Alone it is worse than a constant (1.076 vs 1.007).
- **'L' stations**: passes by 0.005 (0.517 vs 0.522). The margin is within the replicate spread:
  with the agent-based OD of 5 synthetic populations, M_cal is 0.5154, 0.5192, 0.5230, 0.5196,
  0.5228, so 2 of 5 populations (0.5230, 0.5228) do **not** beat B_service (0.5222). The
  pre-registered criterion is on the expected (analytic) OD and passes; the replicates say the
  pass is not robust to the synthetic population.
- **Persistence** is far better than any cross-sectional predictor (0.072 / 0.064): a route or
  station with a year of history is best predicted by that history. The model's use is for
  units or scenarios without history.
- **Period-only holdout** (fit on all units' 2025, test on their 2026): M_cal 0.440 / 0.498,
  B_service 0.460 / 0.503 (bus / 'L').
- **Replicate variance** (build seeds 1-5, 2,000 requested agents): median coefficient of
  variation of a unit's prediction 0.27 (bus) and 0.36 ('L'), 90th percentile 0.71 and 0.73;
  bus M_cal 0.445-0.461, all below B_service 0.473.
- Units with no predicted model demand: 5 bus routes, 2 stations.

### Superseded: mixed counting methods (WS3, train 2024 / test 2025-26)

Kept as recorded; its file is `reports/ridership_validation_superseded_mixed_methods.json`.
Labelled superseded because its training period (2024, old farebox method) and test period
(2025-26, restated APC method) count rides differently. Its numbers are not to be compared with
W1's.


From `python -m simchi.eval.ridership --replicates` (then → `reports/ridership_validation.json`, now `reports/ridership_validation_superseded_mixed_methods.json`).
The design and pass criteria are in the docstring of `simchi/eval/ridership.py`, committed
(3c66780, "WS3 pre-registration") before any 2025-2026 ridership was examined. The 2024 data
of all units had been looked at during development, so the training period is not out of
sample.

**What is predicted.** Expected weekday commute trips by transit between areas (ACS commuters ×
gravity destinations × network mode choice, ×2 for the return trip; 752,452
trips) are loaded onto AM-peak shortest paths of the CTA network from 20 points per area,
giving boardings per bus route and 'L' entries per station. The model has no non-commute
demand, so its level is calibrated. **Units**: 123 bus routes and 121 'L' stations inside the
city with positive ridership in both periods. **Training**: 2024 weekday means; **test**: weekday
means 2025-01-01 to 2026-08-31 (observed totals over the units: buses 559,900 → 621,096
rides per weekday, 'L' 304,849 → 334,780 entries).
**Primary test**: 5 folds of units; each predictor is fitted on the other folds' 2024 means and
predicts the held-out fold's 2025-26 means. Metric: mean absolute log error (MALE; 0.45 means a
typical factor of e^0.45 ≈ 1.57).

| Predictor of log rides | Bus routes | 'L' stations |
|---|---|---|
| B_mean: constant | 1.000 | 0.682 |
| B_service: scheduled weekday trips (log-linear) | 0.476 | 0.496 |
| M_sim: simulation, one scale factor | 0.997 | 0.964 |
| **M_cal: simulation + scheduled trips (log-linear)** | **0.447** | **0.500** |
| Criterion: M_cal below both baselines | **pass** | **fail** |

- **Buses**: calibrated together with scheduled service, the simulation's assigned boardings
  reduce the held-out error from 0.476 to 0.447 (6%). On its own (one scale factor) the
  simulation is no better than a constant (0.997 vs 1.000).
- **'L' stations**: the simulation adds nothing measurable to scheduled service (0.500 vs
  0.496); on its own it is worse than a constant (0.964 vs 0.682). Station entries
  depend on walk-up catchments, airport, event and non-commute travel that a commute model on
  6-20 points per area does not resolve; 2 stations get no predicted entries at all.
- **Period-only holdout** (fit on all units' 2024 means, test on their 2025-26 means): MALE
  M_cal 0.437 / 0.482 (bus / 'L'), B_service 0.461 / 0.489. The **persistence reference** (each
  unit's own 2024 mean) is far better: 0.126 / 0.104. For a route or station with ridership
  history, its history predicts next year much better than the model; the model's use is for
  units or scenarios without history.
- **Replicate variance** (agent-based commute OD of 5 synthetic populations, build seeds 1-5,
  2,000 requested agents): median coefficient of variation of a unit's prediction
  0.27 (bus) and 0.36 ('L'), 90th percentile 0.71 and 0.73; M_cal held-out MALE
  ranges over seeds 0.441-0.458 (bus; all below B_service 0.476) and
  0.496-0.506 ('L'; B_service 0.496). With 2,000 agents, route-level predictions
  from the agents themselves are noisy; the expected (analytic) OD above has no sampling noise.

## Crash safety layer (W4)

`python -m simchi.safety.mirror` (→ `data/raw/mirror/safety/`, aggregates only, pinned in
`data/sources.toml`) and `python -m simchi.safety.crashes` (→ `reports/safety/crash_ranking.json`,
`reports/safety/sites.csv.gz`). Design and pass criterion: docstring of
`simchi/safety/crashes.py`, committed as cb367e0 ("W4 pre-registration") before any crash,
fatality, camera or volume value was downloaded.

**Data.** 877,921 crashes 2018-2025 (85ca-t3if); 7,130 have no location and 1,097 more lie more
than 50 m from any street, so 8,227 (0.9%) are unsnapped, including 117 of 16,017 KA crashes.
11,725 snap to expressways or ramps (not CPD jurisdiction; excluded). 985 Vision Zero deaths, 2 unsnapped.
80,077 sites (54,309 segments, 25,768 intersections), 76,522 ranked after excluding 3,555
expressway sites. Traffic counts (gc7y-n4xa, camera-derived, from October 2020) reach 414
segments, so 987 ranked sites have a volume and the rest are "crash concentration" on the map.

**Deviation found after pre-registration (reported, not corrected).** The Vision Zero dataset
begins 2019-01-03, so 2018 has no K (death) events and its KA counts are A crashes only. The
design was run as registered; this lowers the 2018 contribution to all three rankings' training
data and does not touch the 2025 outcome.

**Result.** 1,530 KA events in 2025 at ranked sites.

| Top k | Empirical Bayes | Raw 2018-2024 | 2024 only |
|---|---|---|---|
| 50 | 2.61% (40) | 2.81% (43) | 2.42% (37) |
| **100 (criterion)** | **4.58% (70)** | **4.64% (71)** | 3.66% (56) |
| 200 | 8.10% (124) | 7.91% (121) | 5.95% (91) |

**Fail**: the empirical-Bayes ranking beats the 2024-only ranking but not raw counts (70 vs 71
events at the pre-registered top 100). It leads at the top 200, which is reported but is not the
criterion. The two top-100 lists share 86 sites. Serious crashes are spread thinly: the top 100
of 76,522 sites hold under 5% of them. Model: NB2, alpha 1.237; coefficients in the report.
Lanes are not in the model (no lane data for sites; not imputed).

**Camera slice (descriptive).** 24 speed cameras went live in 2019-2024; no red-light camera did.
Within 660 ft, 12 months before vs after, against 3 matched intersections each (from 1,647 with
no camera within 1/2 mile): ratio of ratios 1.00 [0.90, 1.12] for all crashes (852 → 869 at
cameras, 2,550 → 2,590 at comparisons) and 1.15 [0.45, 2.34] for KA crashes (10 → 10; 55 → 48).
No change is detectable; the KA counts are too small to say more. Violation counts are mirrored
for context only.

`python -m simchi.briefs crash-ranking` refuses to write a brief, because the test failed.

## Promised vs delivered (W5)

`python -m simchi.commitments` (→ `reports/commitments/status.json`); rules in the docstring of
`simchi/commitments.py`, committed as a87759c ("W5 pre-registration") before any status was
computed; commitments in `data/commitments.toml`, Frequent Network routes and dates in
`data/frequent_network.toml` (CTA pages, read 2026-11-23). Statuses on 2026-11-25:

| Commitment | Status | Computed from |
|---|---|---|
| CTA Frequent Network, scheduled (10 min or better, 6-21 h weekdays, 9-21 h weekends) | not met | 1,793 of 1,794 route-direction-hours (99.9%) on 23 routes in the current timetable; the one short hour is #54 Cicero, direction 1, Sunday 20-21 h (5 trips, 12 min) |
| CTA Frequent Network, delivered | insufficient data | needs the W2 archive's pre-registered 8 weeks |
| Vision Zero: no traffic deaths in 2026 | missed | 82 deaths in 2026 (Vision Zero data through 2026-09-27) |
| Vision Zero: no serious injuries in 2026 | missed | 1,588 incapacitating injuries in 2026 (crash data through 2026-11-25) |
| Deaths -20% and serious injuries -35% by 2020 | not measurable | the plan states no baseline year |
| High Crash Areas -40%; hardship-community deaths -25% by 2020 | not measurable | area boundaries not mirrored; victims' home community is not public |

## Polling archive and delivered service (W2) and seconds per stop (W3)

**W2** (design pre-registered 409f44b, docstring of `simchi/transit/archive.py`): durable,
append-only polling archive as release assets (`.github/workflows/archive.yml`), one ingestion
schema for any polling source, per route x direction x day type x hour metrics computed exactly
from daily sufficient statistics, the Frequent Network delivered check, and the rider-feedback
schema and comparison (`simchi/transit/feedback.py`). Tests on constructed data:
`tests/test_archive.py`, `tests/test_feedback.py`.
**Status: insufficient data.** The pre-registered minimum is 56 days and 8 dates of each day
type; the archive starts with the dates still inside the 14-day artifact retention. No delivered
metric is reported until then, and the commitments tracker shows "insufficient data".
Deviation from the storage paragraph, reported: the repository is public, so release assets are
public; by default only the derived files (daily stats; segment run times without vehicle ids)
are uploaded, and raw positions only if the owner sets `ARCHIVE_RAW=on` (docs/CTA_TERMS.md).
The metrics use only the derived files, so nothing in the design depends on that choice.
No rider feedback has been supplied, so no agreement figure exists.
First archive run (2026-11-26): 2026-11-13 and 2026-11-14 archived from complete artifact
downloads; on 2026-11-15 the workflow token hit GitHub's API rate limit, so that day was built from
an incomplete set of runs and its upload also failed (nothing partial was published). Since then
any failed download marks the date incomplete and it is not uploaded (retried the next run), and
the job waits for the rate-limit reset instead of failing.

**W3** (pre-registered b3a4600, docstring of `simchi/transit/stop_time.py`): segment run-time
regression with route fixed effects and route-clustered errors, then the stop-balancing rerun at
the interval's ends with the pre-registered pass rule. Tests on constructed data recover a known
25 s per stop: `tests/test_stop_time.py`. **Status: insufficient data** (minimum 28 days of
archive and 30 routes). Until then service design keeps its assumed 20 s and stays internal
(not validated).

## Service reliability (scheduled vs observed)

`simchi/transit/reliability.py` (definitions in its docstring, fixed before any polled data
existed) measures, per route, direction, day type and hour: service delivered (vehicles observed
per poll / scheduled vehicles in service by Little's law), headway regularity (CV), bunching
(headways < 0.25 × scheduled), gaps (> 2 × scheduled) and the share of observations CTA flags
as delayed. It is tested on a constructed history with known answers (`tests/test_reliability.py`).

**Observed results: none yet.** The `live.yml` schedule had not started a single run by the
time of this commit (it was added at 14:17 UTC on 12 Nov 2026; GitHub lists the workflow as
active, and this session cannot dispatch it), so there is no polled history and no observed
reliability number to report. `pages.yml` rebuilds the report and the viewer lens daily from
the latest 300 `live.yml` runs once they exist; coverage (runs, polls per hour) is measured, not
assumed.

**Polling bias (simulated).** What the polling design (runs every 5 min, 3 polls 60 s apart)
recovers on a 15 km line with gamma headways (mean 8 min), vehicle speeds varying around 5 m/s,
headways converted from spatial gaps by the median speed, 20 service days per case
(`polling_bias()`; truth = headways at the line's midpoint). Truth / estimate:

| Case | Bunching share | Gap share | Headway CV |
|---|---|---|---|
| headway CV 0.6, equal speeds, every run fires | 0.049 / 0.057 | 0.070 / 0.050 | 0.604 / 0.600 |
| + speed CV 0.1 | 0.123 / 0.142 | 0.089 / 0.064 | 0.687 / 0.697 |
| + 20% of runs skipped, mean delay 60 s | 0.123 / 0.141 | 0.089 / 0.064 | 0.687 / 0.696 |
| + 50% skipped, mean delay 120 s | 0.123 / 0.138 | 0.089 / 0.062 | 0.687 / 0.692 |
| regular line (headway CV 0.3) | 0.070 / 0.085 | 0.029 / 0.024 | 0.510 / 0.521 |
| irregular line (headway CV 1.0) | 0.222 / 0.260 | 0.142 / 0.087 | 1.013 / 0.959 |
| speed CV 0.25 | 0.176 / 0.212 | 0.121 / 0.067 | 0.803 / 0.808 |

- **Gaps are undercounted** (by 0.02 to 0.055 here): a gap is seen only while both vehicles are
  on the line at a poll, so the longest gaps are censored. Treat observed gap shares as lower
  bounds.
- **Bunching is overcounted** (by 0.008 to 0.038), more with more speed variation: vehicles
  that are close in space but moving at different speeds are not as close in time as the gap /
  median-speed conversion implies.
- **Skipped or delayed runs** change the estimates little (bunching 0.142 → 0.141 → 0.138 as
  0%, 20%, 50% of runs are skipped) because snapshots are spread over the day; they reduce the
  number of observations and leave hours unobserved when whole stretches are skipped, which the
  coverage table reports.
- The headway CV is recovered within 0.06 in every case.

**Crime join (descriptive).** Reported violent crime (CPD, 12 months to Oct 2026, aggregated by
community area; all locations and CTA locations separately) is joined to each route by its
length share per area and reported next to the route's reliability with Spearman correlations.
This is an association between places, not an effect in either direction; it waits for
observed reliability data.

## Operations tools (WS7)

Designs and pass criteria are in the module docstrings, committed before any evaluation was run
(d1785df, "WS7 pre-registration").

### Crowding forecast (one week ahead; observed ridership)

`python -m simchi.ops.crowding` (→ `reports/ops/crowding.json`). Forecast of daily rides per bus
route and 'L' station seven days ahead: M_med4 = median of the last 4 days of the same day type
(and, on weekdays, the same weekday) known a week before; baseline B_naive = the same weekday last
week. Test: every day from 1 Jan to 31 Aug 2026. Crowding index = forecast rides per scheduled
vehicle trip (bus) or train departure (station) of that day type.

| | Forecasts | Units | MALE B_naive | MALE M_med4 | Criterion |
|---|---|---|---|---|---|
| Bus routes | 27,946 | 128 | 0.1569 | 0.1339 | **pass** |
| 'L' stations | 34,992 | 144 | 0.1508 | 0.1280 | **pass** |

Mean absolute error in rides: buses 485 → 413, stations 310 → 262. The median of four is better on
every day type (weekday, Saturday, Sunday/holiday) for both modes. Ridership data on the portal
end on 2026-08-31, so the published "next week" is 1-7 Sep 2026, already past; this
is a daily-total forecast, not a live, trip-level crowding prediction (Bus Tracker passenger-load
classes would come from the polled history, which does not exist yet).

### Holding recommender (simulated)

`python -m simchi.ops.holding` (→ `reports/ops/holding.json`). Rule: hold a vehicle running
closer than half the scheduled headway behind its leader by half the difference between its back
and front headways, at most 2 min. Pre-registered test: 40-stop loop, 10 buses, 30 seeds × 6 h,
paired with and without holding at 4 control points; criterion: mean passenger wait lower with
holding, 95% interval below 0.

- **Pre-registered run: fail.** Mean wait 29.58 → 32.15 (Δ +2.58 [+1.57, +3.59]) min; round trip 103.36 → 109.30 (Δ +5.94 [+5.57, +6.32]) min.
- That run had a start-up artifact found after it failed: all buses left the terminal one headway
  apart while passengers at every stop had been accumulating since before service, so the first
  bus met very long dwells and the line started bunched. With the line starting in regular
  operation (buses spread evenly, `start="spread"`, now the default) the same criterion is met
  narrowly: mean wait 25.37 → 24.43 (Δ -0.94 [-1.80, -0.09]) min, bunching share 0.72 → 0.68 (Δ -0.03 [-0.04, -0.02]),
  at a cost of 24.4 min of holding per hour and round trips
  +3.9 min longer. Because this correction followed the failure, the check is
  recorded as failed; the corrected result is reported, not substituted.
- In both versions the simulated line is extremely unstable (bunching share about 0.7 without
  control), so this is a stress test of the rule, not evidence about CTA operations. The live
  ops view (`live/ops.json`, Live CTA panel) shows the rule's advice for bunched vehicles as
  advisory only.

### Live-feed anomaly detection (constructed labels)

`python -m simchi.ops.anomalies` (→ `reports/ops/anomalies.json`). Fixed-threshold detectors
(jump > 35 m/s; stuck < 10 m in 120 s away from terminals; off route > 300 m from every shape of
the route; outage: no vehicle on a route-direction with ≥ 3 scheduled) on a **simulated** base
feed (scheduled vehicles moving along GTFS shapes, GPS noise 15 m, 5% in terminal layovers) with
injected anomalies, 20 seeds, weekday 8 am:

| Detector | TP | FP | FN | Precision | Recall |
|---|---|---|---|---|---|
| jump | 410 | 0 | 17 | 1.000 | 0.960 |
| stuck | 323 | 0 | 87 | 1.000 | 0.788 |
| off_route | 337 | 6 | 97 | 0.983 | 0.776 |
| outage | 80 | 26 | 0 | 0.755 | 1.000 |

- Scoring fix after the first run: vehicles labelled jump, stuck or off-route that an injected
  outage then removed from the feed were counted as misses although they could not be detected.
  They are now dropped from the labels. First-run recalls: jump 0.932, stuck 0.764, off_route 0.766 (precisions and the outage row
  unchanged).
- Every missed jump was a displacement of 2,002-2,281 m from the true position (33-38 m/s if
  covered in 60 s, close to the 35 m/s threshold); every missed stuck vehicle was
  frozen within 276 m of an end of one of its route's shapes (treated as a layover); every missed
  off-route vehicle ended up within 293 m of another shape of its own route (a branch or the
  other direction). All 6 off-route false positives are jump-injected vehicles whose median
  position (per coordinate, over the 3 polls) the jump pulled more than 300 m off the route.
- Outage false positives are route-directions where the simulated base feed itself drew no
  vehicle while ≥ 3 were scheduled (a Poisson draw of 0); in real data they would be genuine
  gaps or feed losses, so the outage precision here is a property of the simulated base.
- No precision or recall on real data exists yet: the polled history is empty (see Service
  reliability).

## Interventions (ranking)

`python -m simchi.interventions --replicates 10` (→ `reports/interventions/`; brief:
`docs/BRIEF.md`). Eight network interventions, each on 10 synthetic populations (build seeds
1-10) against the scheduled network, paired 95% t-intervals; cost proxy = scheduled weekday
vehicle-hours (GTFS); definitions in the module docstring. Ranking (Experiment Lab →
intervention ranking):

| Intervention | Δ vehicle-hours / weekday | Δ transit trips / weekday [95%] | Trips per 1,000 vehicle-hours or per $1,000 [95%] |
|---|---|---|---|
| All 'L' lines: headways ×0.8 | +435 | +21,700 [17,000, 26,300] | 49,800 [39,000, 60,500] |
| All buses: headways ×0.8 | +3,928 | +51,400 [40,200, 62,700] | 13,100 [10,200, 16,000] |
| Frequent network: top-10 bus routes ×0.75 | +1,185 | +11,700 [8,800, 14,600] | 9,900 [7,400, 12,300] |
| Bus priority, top-10 routes (in-vehicle ×0.85, hypothesis) | −533 | +26,900 [20,900, 33,000] | saves vehicle-hours |
| Bus reliability (waits ×0.853, hypothesis) | 0 | +36,100 [27,300, 44,900] | no operating cost modelled |
| Fares −$0.50 | 0 | +83,600 [76,000, 91,200] | 165 [150, 180] per $1,000 |
| Fare-free | 0 | +380,300 [355,200, 405,400] | 120 [112, 128] per $1,000 |
| Late-night service (night headways ×0.5) | +258 | not modelled (AM-peak choice model) | night job access +69,600 (+31%) |

Equity (lowest-income areas, 24.8% of residents): their share of commuter time savings is
15.3% [13.8, 16.9] (top-10 frequency) to 21.0% [19.7, 22.3] (all buses); system-wide frequency
and reliability raise their 45-minute job access more than other areas' (e.g. all 'L' lines
+23,200 vs +10,500 jobs). Caveats (cross-sectional time sensitivity, assumed value of time and
effect sizes, model-scale revenue, train-hours not comparable to bus-hours) are in the brief.

## Service design (frequency re-allocation, stop balancing)

`python -m simchi.service_design --replicates 10` (→ `reports/service_design/`; method in
`docs/DESIGN.md` §10c). Simulated on 10 synthetic populations against today's schedule; paired
95% intervals; vehicle-hours scheduled (GTFS); demand observed (CTA weekday boardings, last 12
months).

| Design | Δ bus vehicle-hours / weekday | Δ transit trips / weekday [95%] | Commuter time saved / weekday [95%] | Share to low-income areas |
|---|---|---|---|---|
| Square-root re-allocation, 100% of today's budget | 0 | +3,930 [−3,408, +11,269] | +1,960 h [+1,591, +2,329] | 1% [−8, 10] |
| Square-root re-allocation, 95% budget | −786 | −7,168 [−12,621, −1,715] | −1,908 h [−2,327, −1,489] | 44% [37, 51] |
| Square-root re-allocation, 90% budget | −1,571 | −20,226 [−27,293, −13,160] | −6,258 h [−6,713, −5,803] | 28% [26, 29] |
| Stop balancing, top-10 routes (20 s per skipped stop, assumed) | −553 | +9,703 [+4,154, +15,252] | +5,178 h [+4,689, +5,668] | 15% [10, 20] |

What this says:

- **Re-allocating today's bus hours by the square-root rule gains no measurable ridership** (the
  interval spans zero) although it saves commuters about 1,960 hours a day; the analytic waiting
  change at observed demand is −168 rider-hours a day. By this criterion CTA's current
  allocation is close to the rule's optimum within the 0.6-1.6× bounds.
- **Cutting bus hours, even with the best allocation, loses riders**: 5% fewer bus-hours (−786 a
  weekday) costs about 7,200 trips; 10% costs about 20,200. Low-income areas carry 28-44% of the
  added waiting, more than their 24.8% population share.
- **Stop balancing is the one design here that both saves bus-hours and gains riders**: removing
  stops closer than 400 m on the ten busiest routes (keeping terminals and transfer points;
  49-106 stop positions per route, both directions) saves 553 scheduled bus-hours a weekday and
  adds about 9,700 trips, *if* each skipped stop saves 20 s. That saving is an assumption, not
  measured; with the live feed running, observed run times before/after could replace it.
- **Caveats of the re-allocation.** The rule moves service towards infrequent routes (up to 1.6×,
  e.g. routes 206, 148, 143) and away from the busiest (route 66 ×0.70, 9 ×0.77, 53 ×0.81),
  because it assumes riders wait half a headway even on hourly routes (where they time their
  arrival) and has no capacity limit (cutting route 66's trips by 30% would crowd it). The route
  list in the viewer is what the formula implies, not an operational recommendation; a version
  with crowding limits and timed-arrival waits is the next step.
- 'L' lines are not re-allocated: rail ridership is published by station, not by line.

## Experiments

Effects are paired differences against the baseline scenario over the same seeds, with
95% t-intervals (10 replicates, 8 for the safety sweep). "*" marks an interval that excludes 0.

### Incident response (baseline: no incidents)

| Scenario | Exposed agent-days | Evening activities cancelled | Perceived safety at end |
|---|---|---|---|
| recorded incidents, no response | +9.8 [7.8, 11.8] * | 0 (exactly) | 0 (exactly) |
| recorded incidents | +9.8 [7.8, 11.8] * | +0.6 [0.1, 1.1] * | −0.0011 [−0.0014, −0.0009] * |
| recorded + simulated | +19.8 [15.8, 23.8] * | +1.7 [0.8, 2.6] * | −0.0023 [−0.0028, −0.0018] * |
| recorded + 3× simulated | +36.3 [28.0, 44.6] * | +3.5 [1.6, 5.4] * | −0.0042 [−0.0051, −0.0032] * |

The exact zeros of the first row are the common-random-numbers guarantee (Corollary 2 in
`DESIGN.md`). All behavioural effects here follow from the **hypothesised** safety
mechanism; they show what that hypothesis implies, not measured behaviour. They are small
because few of the 1,944 agents are out of home within 400 m of one of the day's incidents
(2 to 13 per day in the recorded + simulated run of 5-11 Oct 2020).

### Safety-response strength (baseline: γ = 0)

Cancellations rise roughly in proportion to γ: +1.1 (γ = 0.25), +1.8 (0.5), +3.3 (1.0),
+7.3 (2.0) per week, all with intervals excluding 0.

### Remote work (baseline: ACS work-from-home shares)

| Work-from-home × | Work participation | Car person-km | Transit person-km | Minutes out of home |
|---|---|---|---|---|
| 0.5 | +2.8% * | +0.5% * | +2.9% * | +1.5% * |
| 2 | −6.2% * | −2.7% * | −6.1% * | −3.4% * |
| 4 | −18.6% * | −10.0% * | −13.7% * | −10.1% * |
| 8 | −39.4% * | −22.2% * | −29.1% * | −21.4% * |

Discretionary trip probabilities do not depend on working from home, so the model has no
rebound in non-work travel: the reductions above come from removed commutes only.

### Transit disruption (baseline: scheduled service)

The scenarios change the CTA network (in-vehicle times, headways, fares); riders respond only
through the network-based mode choice (`mode_shift` stays 0). Relative effects, 10 replicates:

| Scenario | Transit trips | Car trips | Transit person-km | Car person-km | Minutes out of home |
|---|---|---|---|---|---|
| bus and rail 1.5× slower | −21.3% [−21.5, −21.0] * | +9.7% * | −20.5% * | +9.6% * | +0.44% * |
| half the frequency | −15.3% [−15.5, −15.0] * | +7.2% * | −14.7% * | +7.1% * | +0.29% * |
| fares +$1 | −9.3% [−9.4, −9.2] * | +4.2% * | −8.5% * | +4.0% * | −0.23% * |

The fare effect rests entirely on the assumed value of time (see above); at $10/h it would be
larger, at $25/h smaller. The intervals are narrow because every replicate uses the same
synthetic city and the same mode draws (a person's mode is a habit drawn once at build time);
they measure day-to-day schedule noise, not uncertainty in the fitted model. In v0.2 slowing
transit changed only trip durations (ridership unchanged) because mode choice used distance.

## Limitations

- Transit times are area-to-area means of AM-peak weekday paths (6 points per area); waits
  are half the scheduled headway (capped at 20 min), with no reliability or crowding; Pace
  and Metra are not modelled (jobs outside Chicago use an assumed regional leg).
- No road network: car trips are straight lines at one fitted door-to-door speed; the street
  grid in the viewer is drawn, not routed. Trip lines in the viewer are straight.
- Fare and transfer sensitivities are not estimable from the ACS data (see above).
- Daily plans use assumed time windows and probabilities (the ATUS reference used by v0.1
  was lost); participation shares are not validated against time-use data.
- The safety mechanism and the social network are hypotheses.
- 2,000 agents represent 2.6 million residents (about 1,330 each); rare events such as
  exposures are noisy per run, which the replicate design addresses.
