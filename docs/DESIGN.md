# SimChicago v0.2: design

SimChicago simulates the daily activities of a synthetic population of Chicago residents,
calibrated to every community area's published statistics, and runs experiments on it:
many scenarios × many random replicates, compared with paired statistics. This document
states every model, the data each part is fitted to, and the properties the code relies on,
with proofs. Measured results are in `docs/EVALUATION.md`; every parameter with its value
and provenance is in `docs/PARAMETERS.md`.

v0.2 is a rewrite. The v0.1 backend and its documents were lost (their files were
zero-filled before they reached this repository); what survived was the README, the test
suite, the viewer and three of the data mirrors. v0.2 was rebuilt to the surviving tests'
interfaces and properties.

## 1. Coordinates and world

All geometry is in metres in UTM zone 16N relative to the centroid of the city, with
x = easting − E₀ and z = −(northing − N₀), so north is −z (the viewer's convention).
The world has the 77 community areas (CDS polygons; one invalid polygon is repaired with
`make_valid`), their jobs (CDS `TOTEMPWRK`, which counts jobs *located* in an area; see §9),
and an "outside Chicago" destination reached through five schematic suburban gateways.

Distances are between area centroids. The intra-zonal distance of an area of size A is the
mean distance between two uniform points in a disc of equal area,
d̄ = 128 R / (45 π), R = √(A/π). The distance to "outside" is the distance to the nearest
gateway plus 5 km (assumption).

Homes are placed in census tracts chosen with probability proportional to 2014 tract
population (SDOH mirror), uniformly within the tract ∩ area.

## 2. Synthetic population

For each area, a pool of candidate households is generated with valid structure: an adult
householder in every household; one-person households non-family; children (< 18) only
in family households; labour status only from age 16; education only from 25. Vehicles
and tenure are drawn with an income gradient (an assumption whose marginals calibration
then corrects).

**Calibration (raking).** Pool weights w are found from design weights d by

  min_w Σ_i w_i log(w_i/d_i) − w_i + d_i + (1/2μ) Σ_k r_k²,  r_k = (Aᵀw − c)_k / c_k,

for 33 controls per area: households (total, size 1/2/3/4+, family, income ×6,
vehicles ×4, owner-occupied) and persons (age bands ×8, employed, unemployed, education ×6),
each set rescaled to a consistent total (person controls scaled from TOT_POP to POP_HH).
Controls with a zero target are removed together with every candidate that has them.

*Proposition 1 (residual identity).* Write Ã = A diag(c)⁻¹ and w(λ) = d ∘ exp(Ãλ). The dual
h(λ) = Σ_i w_i(λ) − Σ_k λ_k + (μ/2)|λ|² is convex with ∇h = Ãᵀw − 1 + μλ and
∇²h = Ãᵀ diag(w) Ã + μI ⪰ 0. At its minimiser ∇h = 0, i.e. r = Ãᵀw − 1 = −μλ.
*Proof.* Differentiate; the Hessian is a Gram matrix plus μI, so h is convex and its
stationary points are minimisers. ∎ With μ = 0 and a feasible problem the controls are met
exactly. The solver is damped Newton with Armijo backtracking on h.
(Test: `test_rake_residual_identity_on_infeasible_problem`.)

**Selection.** k = round(n_area · TOT_HH / POP_HH) households are drawn per area by
systematic PPS on the calibrated weights: with C_i = k Σ_{j≤i} w_j / Σ_j w_j and one uniform
u, unit i is selected once for every point u + m (m = 0..k−1) in (C_{i−1}, C_i].

*Proposition 2.* Unit i is selected ⌊e_i⌋ or ⌈e_i⌉ times, e_i = k w_i / Σ w.
*Proof.* The points are spaced exactly 1 apart; a half-open interval of length e_i contains
either ⌊e_i⌋ or ⌈e_i⌉ of them. ∎ (Test: `test_systematic_pps_selection_counts`.)

Each drawn household has weight TOT_HH / k, so household weights sum to TOT_HH exactly.

## 3. Commute destination

  P(j | i) ∝ exp(V_ij),  V_ij = α log jobs_j − β d_ij + δ·[i = j],  V_i,out = γ₀ + γ₁ d_i,out.

The CDS gives, for each origin i, the five most common work destinations of its residents
with counts n_ik (LEHD), and the employed residents EMP_i. With r_i = EMP_i − Σ_k n_ik the
residents working anywhere else, the log-likelihood

  ℓ = Σ_i [ Σ_k n_ik log P(j_ik | i) + r_i log(1 − Σ_k P(j_ik | i)) ]

uses every employed resident without inventing unlisted flows. Fitted by L-BFGS-B.

## 4. Commute mode

A multinomial logit over car, transit, walk/bike and other, on the level of service of the
trip from area i to destination j (77 areas and "outside Chicago"):

  V_car = b_ivt·T_car,
  V_transit = a_t + b_t·noveh + e_t·outside + b_ivt·IVT + b_wait·WAIT + b_walk·WALK + b_xfer·XFERS + b_fare·FARE,
  V_walk = a_w + b_w·noveh + b_walk·T_walk,  V_other = a_o + b_o·noveh + b_ivt·T_other.

IVT, WAIT, WALK, XFERS and FARE come from the CTA network skim (§5a); T_car, T_walk and
T_other from §5. Area shares are averaged over the area's vehicle-ownership mix and over
destinations with P(j | i), and fitted by grouped maximum likelihood to ACS commuter counts.
Sign constraints: time, wait, walk and transfer coefficients ≤ 0 (more time cannot attract);
no-vehicle effects in [0, 8]. b_fare is not estimable (fares are flat) and is set to
60·b_ivt / VOT with an assumed value of time VOT = $15/h. Estimates, the binding constraints
and identification diagnostics are in `docs/EVALUATION.md`.

Each person's mode is chosen once (a habit) from a stored uniform u_mode by inverse CDF in the
order car, transit, walk, other. **Monotonicity.** If a scenario lowers V_transit for a person
and leaves the other utilities unchanged, P_car rises and P_car + P_transit = 1 − P_walk − P_other
falls, so the interval (P_car, P_car + P_transit] that selects transit shrinks at both ends:
nobody switches *to* transit, and the transit riders under the scenario are a subset of the
baseline's (tested in `tests/test_network.py`).

## 5. Travel time

Car, walk and other: T_m(d) = τ_m + 60 · 1.3 · d / v_m, with circuity 1.3, walking 4.8 km/h
(τ = 0), "other" 15 km/h (τ = 2 min) and car parking τ = 5 min assumed. v_car is fitted by
weighted least squares to each area's ACS mean commute time AGG_TT / TOT_COMM; because the
mode shares depend on T_car, the car speed and the mode-choice model are fitted alternately
until v_car changes by less than 0.01 km/h. Transit trips take the skim's walk + wait +
in-vehicle minutes between the areas of the trip's ends (looked up on a 250 m area grid); trips
not placed in an area use a least-squares line through the skim.

## 5a. Transit network (CTA GTFS)

`simchi/transit/network.py` builds a graph from the GTFS extract: each used stop appears twice
(departure side, arrival side) so that every path boards at least one vehicle; each pattern
position is a node. Edges: walk access/egress between zone points and stops within 800 m (the
3 nearest if none), walk transfers between stops within 250 m (1.3 × straight line at 4.8 km/h);
boarding with wait = half the scheduled headway of all trips of the same route and direction
serving that stop and the pattern's next stop in the band (weekday 6-9 am), capped at 20 min;
riding with the median scheduled in-vehicle time between consecutive stops in the band.
Paths minimise ivt + 2·wait + 2·walk + 5 min per boarding (assumed weights); a path's
components are reported unweighted. Dijkstra (scipy) gives the shortest-path tree from each of
462 zone points (6 per area, by tract population, fixed seed); components are summed along the
tree by pointer doubling (round r adds the values of the 2^r-th ancestor's path segment;
⌈log₂ depth⌉ rounds), checked against explicit path tracing in the tests. Area-to-area values
are means over point pairs (a point is not paired with itself). Jobs outside Chicago are reached
by an assumed regional leg from stops near the area's nearest gateway. Fares: $2.50 if the path
uses the 'L', else $2.25 (CTA fares page, 2026-11-12). Scenario knobs scale headways and
in-vehicle times by mode or route and set fares; each scenario's skim takes about 17 s and is
cached on disk.

## 6. Daily plans

Each person starts and ends every day at home. Work (start N(510, 50) min, duration
N(510, 45) min, p = 0.92 weekdays / 0.20 weekends), school (08:00-15:00, ages 5-17) and
aftercare (to 19:00, for children ≤ 12 whose household adults all commute) are placed
first. Up to three discretionary activities (shop, social, leisure, errand) are drawn with
day-type probabilities and time windows and inserted where they fit with their travel time;
45% of discretionary trips stay within 1 km of home, the rest choose an area with
P(j | i) ∝ jobs_j^½ households_j^½ e^(−0.35 d_ij). Trips under 1.5 km are walked. The
work probabilities and durations, school and aftercare times, activity probabilities and
windows and the 1.5 km walking threshold are scenario defaults taken from the v0.1 exported
configuration; the work start-time distribution, the cap of three discretionary activities,
the 45% local-trip share and the 0.35 /km decay are new v0.2 assumptions.

The plan of a person-day is a list of segments (t₀, t₁, kind, x₀, z₀, x₁, z₁, mode) that
partitions [0, 1440] (validated for every agent-day; `test_every_day_plan_is_a_partition_of_the_day`).

**Common random numbers.** Day d draws one matrix of uniforms U_d ∈ [0,1)^{n×48} from a
stream seeded (seed, d), and each person-day consumes its row in a fixed order, whether or
not a draw is used. Simulated incidents use a separate stream (seed, d, 1000003). Two
scenarios with the same seed therefore share every random number, and differ only through
the decisions their settings change.

## 7. Incidents

Recorded incidents (CPD, IUCR 0325/0326, 2020) are replayed at their recorded time and place
(label `observed`). Simulated incidents (label `simulated`) are drawn from

  N_d ~ Poisson(L ω_weekday(d)),  hour ~ η,  areas ~ Multinomial(N_d, p), p ~ Dirichlet(α π),

fitted on 1 Jan - 30 Sep 2020 (before the default simulated week). π, η, ω are add-½
smoothed frequencies (Σπ = Ση = 1, mean ω = 1) and α maximises the Dirichlet-multinomial
likelihood of the weekly area-count vectors (`dm_loglik`, checked against the direct formula
in `test_dirichlet_multinomial_loglik_against_direct_formula`).

**Exposure.** A person who is out of home (at an activity or travelling) within `radius_m`
(400 m) of an incident at the minute it happens is directly exposed; people at home are
indoors. E_aware,i is the number of i's network contacts directly exposed that day.

## 8. Perceived safety (hypothesis)

No data inform this mechanism; it is labelled `hypothesis` everywhere. Each person has a
baseline s̄_i ∈ [0.4, 0.95], decreasing in the home tract's 2015 violent-crime rate. Daily,

  s ← F(s) = ((1−η−c) s + η s̄ + c W s) ∘ (1−a)^{E_direct} ∘ (1−b)^{E_aware},

with W the row-stochastic social-network matrix (household 1.0, coworker 0.5, neighbour 0.5
before normalisation; up to 3 coworkers and 3 nearest neighbours each).

*Theorem 1.* Let W ≥ 0 be row-stochastic, η, c ≥ 0, η + c ≤ 1, a, b ∈ [0, 1], exposures ≥ 0
and s̄ ∈ [0,1]ⁿ. Then (i) s ∈ [0,1]ⁿ implies F(s) ∈ [0,1]ⁿ; (ii) without exposure,
‖F(x) − F(y)‖_∞ ≤ (1−η)‖x − y‖_∞.
*Proof.* (i) Each component of the bracket is a convex combination of s_i, s̄_i and
(Ws)_i = Σ_j W_ij s_j, all in [0,1], with weights 1−η−c, η, c ≥ 0 summing to 1; the factors
(1−a)^E, (1−b)^E lie in [0,1]. (ii) Without exposure F(x) − F(y) = (1−η−c)(x−y) + cW(x−y)
and |(W v)_i| ≤ Σ_j W_ij |v_j| ≤ ‖v‖_∞, so each component is at most (1−η−c+c)‖x−y‖_∞. ∎
(Test: `test_safety_theorem_invariance_and_contraction`.)

*Corollary 1 (equilibrium).* For η > 0 the no-exposure map has a unique fixed point s*,
the solution of (ηI + c(I − W)) s* = η s̄. That matrix is strictly diagonally dominant
(diagonal η + c(1 − W_ii), off-diagonal row sum c(1 − W_ii)), hence non-singular.
*Proof.* (ii) and Banach's fixed-point theorem give existence and uniqueness; rearranging
s* = F(s*) gives the linear system. ∎ It is computed by the Jacobi iteration
s ← (η s̄ + c W s)/(η + c), a max-norm contraction with factor c/(η + c) (the same bound on
|(Wv)_i| as in the proof of Theorem 1), so it converges geometrically using sparse products only.

*Corollary 2 (no spurious response).* Starting at s₀ = s*, every trajectory satisfies
s_t ≤ s* componentwise, and s_t = s* for all t if there is no exposure.
*Proof.* The no-exposure map F₀ has non-negative coefficients, so it is monotone; exposure
factors are ≤ 1, so F(s) ≤ F₀(s). If s_t ≤ s*, then s_{t+1} = F(s_t) ≤ F₀(s_t) ≤ F₀(s*) = s*. ∎

Everyone starts at s*. An evening discretionary activity (start ≥ 18:00) is cancelled with
probability min(1, γ κ_i (s*_i − s_i)/s*_i), with κ_i ~ LogNormal(0, 0.25) an individual
sensitivity. By Corollary 2 this deficit is ≥ 0, and it is exactly 0 without incidents, so
a run with no behavioural response (a = b = γ = 0) and a run with no incidents produce
identical plans (`test_no_response_equals_no_incidents_common_random_numbers`). In v0.1's
form (deficit measured from s̄) the network term alone moves s away from s̄ and caused
cancellations with no incidents at all; v0.2 corrects this.

## 9. LEHD field orientation

`TOTEMPWRK` counts jobs located in the area (the Loop: 441,233 against 24,703 employed
residents). `WRKCITY1..5` list where an area's workers live, so their counts are bounded by
`TOTEMPWRK` (largest share 0.82); `RESCITY1..5` list where its residents work, bounded by
`EMP` (largest share 0.92). Both bounds are checked by `cds_identities` in the validation.

## 10. Experiments

An experiment is a TOML file of scenarios (dotted SimConfig overrides) and sweeps, run on
one built city with the same replicate seeds for every scenario, in parallel worker
processes (fork, so workers share the built city). For each metric and scenario s ≠ baseline,
the paired differences d_r = m(s, r) − m(baseline, r) over seeds r give the effect estimate
d̄, its standard error and a 95% t-interval; an effect is flagged when the interval excludes 0.
Pairing on common random numbers removes the replicate noise that the scenarios share
(identical scenarios give a difference of exactly 0: `test_paired_effect_of_identical_scenarios_is_exactly_zero`).

Scenario knobs: incident mode; safety parameters; `wfh_multiplier` (scales each area's ACS
work-from-home share); `mode_shift.{transit,walk,other}` (utility shifts); `time_multiplier.*`
(travel-time multipliers per mode); `simulated_incident_multiplier`; schedule parameters
(e.g. `schedule.discretionary_multiplier`); `local_trip_share`; `n_days`, `start_date`.

## 11. Viewer

three.js r180 with a post-processing chain (render → bloom → FXAA → output with ACES tone
mapping). The sky is the Preetham model lit by the sun position of the simulated time
(NOAA algorithm, `core.js`), with a star field after dusk and a sky-only environment map for
reflections. The ground draws Chicago's street grid (no road data): origin at State & Madison,
rotated by the UTM grid convergence computed from two points on one meridian, half-mile
arterials and 1/8 × 1/16-mile blocks, sodium-lit at night with energy-conserving line
anti-aliasing. Buildings are procedural (counts from households and jobs, heights from each
area's housing-structure mix and job density, empty land in proportion to CMAP open space),
with a window shader whose level of detail merges windows in powers of two when they fall
below ~3.5 px. Residents are glowing points coloured by activity (additive at night, normal
blending by day) with motion trails, and close-up people/cars/buses. The Experiment Lab
reads the exported experiments.
