"""Durable, append-only polling history and reliability over the whole archive
(python -m simchi.transit.archive build|aggregate).

PRE-REGISTERED DESIGN, W2 (committed as "W2 pre-registration" before any archive was built;
the 14-day workflow artifacts had been used before only by simchi.transit.reliability)

STORAGE
  GitHub release assets, outside git history and outside Actions' 14-day artifact retention.
  One release per year, tag "history-<YYYY>" (GitHub allows up to 1000 assets per release, each
  under 2 GiB, no total size or bandwidth limit; docs.github.com "About releases", read
  2026-11-25). Per UTC date D two assets:
    vehicles-<D>.csv.gz   every observation of that date in the ingestion schema
    stats-<D>.csv.gz      the date's sufficient statistics (below)
  Append-only: an asset that exists is never replaced (uploads run without --clobber; an existing
  name is skipped and logged). A vehicles file over 200 MB compressed is not uploaded and the job
  fails loudly (size cap). Built daily by .github/workflows/archive.yml from the live.yml run
  artifacts still within retention (backfilling any missing date of the last 13 days). It makes no
  CTA request. Retention: indefinite (release assets are not subject to artifact retention).

INGESTION SCHEMA (one row per vehicle observation; any polling source can be dropped in)
  source         who observed it, e.g. "cta-bustracker", "cta-traintracker", or another name
  mode           bus | train
  route          route id as in the CTA GTFS extract (bus "9", train "Red", "Brn", ...)
  direction      the source's own direction code, text: Bus Tracker pattern "pid:<n>", Train
                 Tracker "trDr:<n>", or any code consistent within the source (the analysis infers
                 GTFS direction from movement and uses this code only as a fallback)
  vehicle_id     text, unique within source
  timestamp_utc  when the vehicle reported this position (ISO 8601, UTC)
  poll_utc       when the observation was taken (ISO 8601, UTC); may be empty, then the
                 timestamp rounded down to the minute is used
  lat, lon       WGS84 degrees
  delay_flag     1 / 0, or empty when the source has none (CTA: Bus Tracker dly, Train Tracker isDly)
  run            groups consecutive observations of one polling session (live.yml run id); may be
                 empty, then source + UTC hour is used
  Rows failing the schema (missing route, vehicle_id, timestamp or position; position outside the
  CTA service box of simchi.transit.live) are dropped and counted.

METRICS (per route x direction x day type x hour, over the whole archive; definitions of
simchi.transit.reliability: headway from positions and median speed, scheduled headway from GTFS)
  delivered/scheduled vehicles  mean vehicles observed per poll / scheduled vehicles in service
  headway CV                    std / mean of all headways of the cell (population std)
  bunching, gaps                shares below 0.25x / above 2x the scheduled headway. Reported as
                                LOWER BOUNDS for gaps (the measured polling bias: polling misses
                                gaps; simchi.transit.reliability.polling_bias)
  coverage                      system polls observed in the cell's day type and hour / polls the
                                polling plan expects (60 per hour per date of that day type: 12 runs
                                x 5 polls), and distinct dates contributing headways
  Sufficient statistics per day make the archive totals exact: polls, sum of vehicles per poll,
  observations, delay-flagged observations, headway count, sum, sum of squares, bunching count,
  gap count, and distinct dates.

MINIMUM AND COVERAGE (fixed now; nothing is reported as a result before the minimum)
  Minimum archive: first to last archived date spans >= 56 days (8 weeks) and each day type has
  >= 8 distinct dates. Until then the report states "insufficient data" with the coverage so far.
  Per-cell coverage threshold: a route-direction-day type-hour cell is eligible only if its
  system poll coverage is >= 0.5, it has headways from >= 4 distinct dates, and >= 30 headways.
  Cells under the threshold are excluded and listed; they are never filled in or imputed.

FREQUENT NETWORK DELIVERED CHECK
  Routes and windows from data/frequent_network.toml (weekdays 6-20 h start hours, weekends
  9-20 h); only dates on or after the route's effective_by. A cell meets the standard if its mean
  observed headway is <= 10 min. Reported: share of eligible cells meeting it, per route and
  overall, and the excluded cells. Because polling undercounts gaps, the share meeting is an
  upper bound on compliance.

RIDER FEEDBACK (schema and comparison; no pass criterion, nothing is tuned to it)
  Schema: route, stop_id (CTA GTFS stop id), timestamp_utc, observed_wait_min, source.
  Each record is matched to its stop's route-direction (the GTFS patterns serving the stop on that
  route; if two directions serve it, both are averaged) and the cell of its Chicago day type and
  hour; predicted mean wait = E[H] (1 + CV^2) / 2 from that cell's archive statistics (random
  arrivals). Reported: records matched, Spearman correlation of observed vs predicted wait,
  median ratio observed / predicted, mean absolute difference in minutes, share within +-50%.
"""
