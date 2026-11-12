# Evaluation

All numbers below come from `python -m simchi.cli validate` (→ `reports/validation.json`)
and the experiment runs in `reports/experiments/*/experiment.json`, on the default build:
2,000 requested agents (1,944 drawn, standing for 2,589,487 household residents), seed 1.

Every model check is **out of sample** and compares against a **simple baseline**, with the
pass criterion fixed before the results were seen. One check (commute destinations) fails
that criterion; it is reported as a failure, not re-defined. v0.3 workstream 2 replaced the
distance-based mode choice and travel times by CTA-network ones; the two checks that failed in
v0.2 (mode choice 8/9 districts, commute time 3.74 vs 3.69 min) were re-run under the same
criteria and now pass (numbers below).

## Validation

| Check | Result | Criterion | Outcome |
|---|---|---|---|
| Data integrity | 3/3 mirrors match their pinned sha256 | all match | **pass** |
| CDS count identities | 12 identities hold within 1.22% in every area; LEHD orientation bounds hold | < 1.5% and bounds hold | **pass** |
| Calibration | 77/77 areas, max relative deviation 1.9 × 10⁻⁹; household weights / TOT_HH = 1.000000; person weights / POP_HH = 0.9773 | < 10⁻⁶; exact; within 3% | **pass** |
| Commute destinations (gravity), leave one district out | held-out log-likelihood better than jobs-proportional destinations in 8 of 9 districts (worse in the Far Southwest Side); in-sample correlation of the 385 listed top-5 shares 0.919, mean absolute error 3.0 share points | better in every district | **fail** |
| Commute mode (network level of service), leave one district out | better than city-wide shares in 9 of 9 districts; in-sample area correlations car 0.88, transit 0.81, walk 0.85, other 0.32 | better in every district | **pass** (v0.2 distance model: 8/9, fail) |
| Commute time (network transit times), leave one district out | mean absolute error 3.51 min against 3.69 min for predicting the city mean; lower in only 2 of 9 districts; in-sample correlation 0.47 | lower error than the city mean | **pass** (v0.2: 3.74 min, fail) |
| CTA GTFS extract | built from the pinned feed; 132 routes (8 rail), 143 stations, 357 patterns covering on average 95.8% of each route-direction's weekday trips | matches pinned sha256 | **pass** |
| Incident forecast (train Jan-Sep 2020, test Oct-Dec) | weekly area counts (13 weeks, 508 incidents): log score −1976.1 (model) vs −2203.1 (population-proportional) and −2206.7 (uniform) | beat both baselines | **pass** |
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
