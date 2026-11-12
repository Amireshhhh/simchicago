# Datasets

All data are local mirrors pinned by sha256 in `data/sources.toml`; the checksums are
verified by `pytest tests/test_data.py` and `python -m simchi.cli validate`. No network
access is needed to build or run anything.

| Key | File | Contents | Used for |
|---|---|---|---|
| `cds_2021` | `data/raw/mirror/Chicago_2020.geojson` | CMAP Community Data Snapshots: 77 community-area polygons with 216 attributes (ACS 2015-2019 and LEHD per the v0.1 metadata) | area boundaries; population calibration; commute destination, mode and time fits; jobs; viewer lenses and procedural buildings |
| `carjackings_2020` | `data/raw/mirror/Chi_Carjackings.geojson` | 1,412 CPD vehicular-hijacking records of 2020: IUCR 0325 (481) and 0326 (931), block-level location, community area | replayed incidents; intensity-model fit and out-of-sample test |
| `sdoh_tracts_2014` | `data/raw/mirror/Chi-SDOH.geojson` | 791 census tracts (2010) with 2014 indicators, including population and the 2015 violent-crime rate | home placement within areas (by tract population); baseline perceived safety (hypothesis) |
| `gtfs_cta` | not stored; derived extract in `data/transit/` | CTA GTFS static feed (zip, ~51 MB, sha256 `ddbf306e…72b4`, last modified 10 Nov 2026): 132 routes (124 bus, 8 rail), stops, trips, stop times, shapes, calendar | real network for the viewer; network transit times for mode choice and trip durations; scheduled headways |
| CTA live positions | not stored in git; workflow artifacts | Bus Tracker `getvehicles` and Train Tracker `ttpositions`, 3 polls per scheduled run | live layer; reliability and operations analyses |
| `cta_l_station_daily` | `data/raw/mirror/l_station_daily.csv.gz` (0.9 MB) | City of Chicago data portal 5neh-572f, "CTA - Ridership - 'L' Station Entries - Daily Totals": 140,074 rows, 2024-01-01 to 2026-08-31 (station id, name, date, day type, entries) | ridership calibration and held-out validation (stations) |
| `cta_bus_route_daily` | `data/raw/mirror/bus_route_daily.csv.gz` (0.6 MB) | City of Chicago data portal jyb9-n7fm, "CTA - Ridership - Bus Routes - Daily Totals by Route": 111,918 rows, 2024-01-01 to 2026-08-31 | ridership calibration and held-out validation (routes) |
| `crimes_all_by_area`, `crimes_cta_by_area` | `data/raw/mirror/crimes_*_by_area.csv.gz` (13 kB) | City of Chicago data portal ijzp-q8t2 (CPD reported crimes), 12 months to 31 Oct 2026, **counts only**, by community area and primary type (and location description for locations starting with "CTA") | descriptive crime join of the reliability report (not causal) |
| landmarks | `data/reference/landmarks.json` | 5 tallest buildings: name, height, coordinates | viewer only; copied from the v0.1 export (which cites Wikipedia, 2026-10-14), not re-verified |

## Checks on the data

- **Count identities** (12, e.g. age bands sum to total population, commute modes to
  commuters): all hold within 1.22% relative difference in every area (`cds_identities`).
- **LEHD orientation**: `TOTEMPWRK` counts jobs located in an area; `WRKCITY*` (where an
  area's workers live) are bounded by it and `RESCITY*` (where its residents work) by `EMP`.
- **Incident records**: 97.7% of points fall inside the community area the CPD record lists
  (locations are block-level and privacy-shifted); 3 fall outside every area polygon.
- **Polygons**: one community-area polygon is invalid as published and is repaired with
  `shapely.make_valid`; all 791 tracts are valid.

## City of Chicago data portal: terms

The portal's datasets used here (community areas, CPD records, CTA ridership) are published
under the City of Chicago Data Terms of Use (https://www.chicago.gov/city/en/narr/foia/data_disclaimer.html,
read 2026-11-12). They ask any secondary or derivative application to display this disclaimer
where it can be accessed, which the viewer (footer) and the README do:

> "This site provides applications using data that has been modified for use from its original
> source, www.cityofchicago.org, the official website of the City of Chicago. The City of
> Chicago makes no claims as to the content, accuracy, timeliness, or completeness of any of the
> data provided at this site. The data provided at this site is subject to change at any time.
> It is understood that the data provided at this site is being used at one's own risk."

The terms also let the City require a user to stop displaying or distributing its data, and
include an indemnity clause. The ridership mirrors are aggregated counts (daily totals per route
or station), not individual records. Refresh: re-run the queries recorded in
`data/sources.toml` (`query`), update the sha256 and re-run `python -m simchi.eval.ridership`.

## Lost in the v0.1 → v0.2 recovery

These v0.1 files reached the repository zero-filled and could not be recovered, so v0.2
does not use them: the CDS field-description PDF, the community-area shapefile archive
(`Chi-CCA.zip`, redundant with the CDS polygons), the ATUS 2025 table-1 transcription, the
precomputed distance matrix and the v0.1 validation report. The surviving test that checked
the ATUS transcription was removed.

## Fetching official data

The v0.1 fetch commands were lost with the backend and are not reimplemented in v0.2;
mirrors must be replaced by hand and their sha256 updated in `data/sources.toml`.

## CTA GTFS extract

`data/transit/` is derived from the feed pinned in `data/sources.toml` (`meta.json` records its
sha256). Reference service days: Tuesday 17, Saturday 21 and Sunday 22 November 2026 (the only
calendar exceptions in the feed are Thanksgiving and Christmas). Patterns: for each route and
direction, trips are grouped by their first and last stop and every group with at least 10% of
the route-direction's weekday trips is kept, represented by its most frequent stop sequence;
on average the kept patterns cover 95.8% of each route-direction's weekday trips. Grouping by
terminals matters: every Yellow Line trip is coded `direction_id` 1, in both directions.
Each pattern also records its trips per time band and day type (`trips_band`), counted over
all trips with the same route, direction and terminals; the network model derives headways from
them. Shapes are simplified to 5 m.

**Refresh.** CTA keeps one package online and replaces it every week or two.
`python scripts/fetch_gtfs.py` downloads it and refuses to rebuild if the hash changed;
`--refresh` adopts the new feed, rebuilds the extract and updates the pinned hash. Re-run the
tests and `python -m simchi.cli validate` afterwards.

## Live positions: storage and retention

`pages.yml` downloads the artifacts of the latest 300 successful `live.yml` runs (about a day)
each time it runs (on push and daily) and publishes only aggregated per-route metrics
(`data/reliability.json`, `data/reliability_summary.json`).

Each `live.yml` run uploads `history.csv.gz` (one row per vehicle per poll: position, heading,
route, CTA timestamp, delay flag, trip and pattern ids, passenger-load class for buses) and
`requests.json` as the artifact `vehicles-<run id>`, retained 14 days. The latest snapshot is
kept in the Actions cache `live-latest-<run id>` (GitHub evicts old caches) so `pages.yml` can
include it. Nothing from polling is committed to git.
