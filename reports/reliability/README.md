# Reliability: scheduled vs observed CTA service

Built by `python -m simchi.transit.reliability <history dir> --out reports/reliability`
from the vehicle histories that `live.yml` keeps as workflow artifacts (`vehicles-<run id>`,
14 days). `pages.yml` rebuilds it daily from the latest 300 successful `live.yml` runs and
publishes the aggregated per-route metrics to the site (`data/reliability.json`, viewer lens
"Bus reliability"; `data/reliability_summary.json`).

**Status of the committed report (2026-11-12): no observed data.** `live.yml` had not run
once when this report was generated (see `docs/EVALUATION.md`), so `summary.json` holds only
the coverage (0 runs) and the simulated polling-bias study. `routes.csv`, `route_hour.csv`
and `crime_join_routes.csv` appear once polled history exists.

Files (when data exist):
- `summary.json`: definitions, measured coverage (runs, polls, hours), system medians,
  simulated polling bias, descriptive crime join (Spearman correlations; not causal)
- `routes.csv`: per route: service delivered, flagged-delayed share, bunching, gaps, headway CV
- `route_hour.csv`: the same per route, direction, day type and hour, with scheduled headway
  and scheduled vehicles in service
- `crime_join_routes.csv`: route exposure to reported violent crime (per 1,000 residents,
  length-weighted over community areas) next to its reliability

Labels: positions and delay flags are **observed**; headways and vehicles in service are
**scheduled** (GTFS); the polling-bias study is **simulated**.
