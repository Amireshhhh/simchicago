# Brief: what would move CTA ridership, per unit of cost (simulated)

*SimChicago v0.3, 12 November 2026. All behavioural numbers are **simulated**; costs are
**scheduled** vehicle-hours from CTA's GTFS timetable. Source: `python -m simchi.interventions
--replicates 10` → `reports/interventions/` (10 synthetic populations of ~2,000 residents
standing for 2.6 million; paired 95% intervals). SimChicago is not affiliated with or endorsed
by CTA.*

## Bottom line

1. **Per added vehicle-hour, more frequent 'L' service moves the most riders**: about 50,000
   simulated weekday transit trips per 1,000 added train-hours [39,000-61,000], against 13,000
   [10,000-16,000] for more frequent buses and 9,900 [7,400-12,300] for a frequent network on the
   ten busiest bus routes. A train-hour and a bus-hour are not the same cost (a GTFS train trip is
   a whole multi-car train), and SimChicago has no cost per vehicle-hour by mode, so compare these
   numbers within a mode, not across modes.
2. **Bus priority on the ten busiest routes** (assumed 15% faster) adds 26,900 trips
   [20,900-33,000] and *saves* 533 scheduled bus-hours a day; its capital and enforcement costs
   are not modelled.
3. **More regular buses** (waits ×0.85, i.e. headway CV 0.6 → 0.4, both assumed) add 36,100 trips
   [27,300-44,900] with no added vehicle-hours; how to achieve it (and what it costs) is outside
   the model, and the simulated holding rule (one way to do it) failed its pre-registered test.
4. **Fares**: −$0.50 adds 83,600 trips [76,000-91,200] for about 165 trips per $1,000 of weekday
   fare revenue forgone; fare-free adds 380,000 [355,000-405,000] at 120 per $1,000. These rest on
   an **assumed value of time ($15/h)**: the fare response is not estimated from data.
5. **Late-night service** (night headways halved, 258 added vehicle-hours) raises the jobs
   reachable within 60 minutes at night by 69,600 per resident on average (+31% over 226,900),
   but SimChicago cannot say how many riders it adds: its mode choice describes AM-peak commutes.

## Equity

Residents of the lowest-income community areas (23 areas, 24.8% of residents) receive:

| Intervention | Share of commuter time savings | Jobs reachable in 45 min: gain, low-income areas / others |
|---|---|---|
| All 'L' lines ×0.8 headways | 20.0% [18.1, 21.9] | +23,200 / +10,500 |
| All buses ×0.8 headways | 21.0% [19.7, 22.3] | +34,700 / +24,400 |
| Bus reliability (waits ×0.85) | 20.7% [19.5, 21.9] | +26,000 / +17,800 |
| Bus priority, top-10 routes | 17.3% [14.3, 20.3] | +14,400 / +15,500 |
| Frequent network, top-10 routes | 15.3% [13.8, 16.9] | +7,000 / +8,200 |
| Late-night service (60 min, night) | not modelled | +58,800 / +73,200 |

Under every intervention the low-income areas receive less than their 24.8% population share of
commuter time savings (the upper ends of all intervals are below 24.8%). System-wide frequency
and reliability improvements raise their job access more than elsewhere; the top-10-route
measures and late-night service raise it less.

## Full ranking

| Intervention | Added weekday vehicle-hours | Δ transit trips / weekday [95%] | Ranked by | Value [95%] |
|---|---|---|---|---|
| All 'L' lines: headways ×0.8 | +435 | +21,700 [17,000, 26,300] | trips per 1,000 vehicle-hours | 49,800 [39,000, 60,500] |
| All buses: headways ×0.8 | +3,928 | +51,400 [40,200, 62,700] | trips per 1,000 vehicle-hours | 13,100 [10,200, 16,000] |
| Frequent network: top-10 bus routes, headways ×0.75 | +1,185 | +11,700 [8,800, 14,600] | trips per 1,000 vehicle-hours | 9,900 [7,400, 12,300] |
| Bus priority, top-10 routes (in-vehicle ×0.85, assumed) | −533 | +26,900 [20,900, 33,000] | saves vehicle-hours; capital cost not modelled | |
| Bus reliability (waits ×0.853, assumed) | 0 | +36,100 [27,300, 44,900] | no operating cost modelled | |
| Fares −$0.50 | 0 | +83,600 [76,000, 91,200] | trips per $1,000 revenue forgone | 165 [150, 180] |
| Fare-free CTA | 0 | +380,300 [355,200, 405,400] | trips per $1,000 revenue forgone | 120 [112, 128] |
| Late-night service (night headways ×0.5) | +258 | not modelled | | |

Top-10 bus routes by 2024 weekday ridership: 66, 8, 9, 79, 53, 77, 3, 49, 82, 22.

## How far to trust this

- **The response to time is not a validated causal effect.** The mode-choice model's
  in-vehicle-time coefficient is estimated from differences between community areas (implied
  elasticity of the transit share −1.6), which also differ in parking, density and income that the
  model does not see; the time-based gains above are what that cross-sectional estimate implies,
  not measured responses, and fares are compared with them only through an assumed value of time.
- **Ridership level.** Simulated transit trips (about 1.2 million a weekday) count every leg of
  every simulated resident's day; they are not CTA boardings. Revenue figures (e.g. −$507,000 a
  weekday for −$0.50) use that level and the full fare and ignore passes, reduced fares and
  transfers, so they overstate real revenue effects.
- **Validation.** The mode choice beats simple baselines on held-out districts; bus-route
  ridership patterns are predicted better than by service levels alone, 'L' station patterns are
  not (`docs/EVALUATION.md`). No intervention effect has been validated against a real service
  change.
- **Not modelled**: crowding and capacity, operator availability, capital costs, Pace and Metra,
  induced non-commute travel beyond the habit-based mode of each resident, and reliability as
  observed (the polling history needed for it does not exist yet).
