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
| CTA live positions | not stored in git; workflow artifacts (14 days) | Bus Tracker `getvehicles` and Train Tracker `ttpositions`, 5 polls per scheduled run | live layer; reliability and operations analyses |
| polling archive (W2) | release assets `history-<YYYY>` (not git) | daily `stats2-<date>.csv.gz` (sufficient statistics per route, direction, day type and hour, with the date's day type and scheduled trips and vehicles in service from the GTFS feed in effect and its sha256; W2 amendment 1), `traversals-<date>.csv.gz` (bus segment run times) and `train_station_headways-<date>.csv.gz` (below); `stats-<date>.csv.gz` from before the amendment are kept and superseded; raw `vehicles-<date>.csv.gz` only if `ARCHIVE_RAW=on`. Ingestion schema for any other source: docstring of `simchi/transit/archive.py` | reliability over the archive, Frequent Network delivered check, seconds per stop (W3), train gaps (W10) |
| train station headways (W10 input) | release assets `train_station_headways-<date>.csv.gz` | station_id, line, direction (Train Tracker trDr), arrival_utc, headway_min, continuous. An arrival at station S is the midpoint between the last observation of a train with next station S and the next observation of that train (at most 150 s apart), so its error is at most half that gap; continuous = no hole over 150 s in the polling between the two arrivals (otherwise an arrival can be missed and the headway is an upper bound). Derived from the Train Tracker next-station field in the live.yml artifacts; backfilled for every date whose artifacts were still within the 14-day retention on 2026-11-26. No vehicle ids | per-station gaps (W10) |
| `calendar` | `data/transit/calendar.json` | day type of each date covered by the pinned GTFS feed (sha256 recorded in the file), by W2 amendment 1: 2026-11-26, 11-27, 12-25, 12-26 are holidays; coverage 2026-10-29 to 2026-12-31 (later dates are "unknown" until a newer feed is pinned; the archive job uses the feed in effect each day) | day types for reliability and the archive |
| `cta_l_station_daily` | `data/raw/mirror/l_station_daily.csv.gz` (0.9 MB) | City of Chicago data portal 5neh-572f, "CTA - Ridership - 'L' Station Entries - Daily Totals": 140,074 rows, 2024-01-01 to 2026-08-31 (station id, name, date, day type, entries) | ridership calibration and held-out validation (stations); method break 2025-01-01, see below |
| `cta_bus_route_daily` | `data/raw/mirror/bus_route_daily.csv.gz` (0.6 MB) | City of Chicago data portal jyb9-n7fm, "CTA - Ridership - Bus Routes - Daily Totals by Route": 111,918 rows, 2024-01-01 to 2026-08-31 | ridership calibration and held-out validation (routes); method break 2025-01-01, see below |
| `crimes_all_by_area`, `crimes_cta_by_area` | `data/raw/mirror/crimes_*_by_area.csv.gz` (13 kB) | City of Chicago data portal ijzp-q8t2 (CPD reported crimes), 12 months to 31 Oct 2026, **counts only**, by community area and primary type (and location description for locations starting with "CTA") | descriptive crime join of the reliability report (not causal) |
| `street_centerlines` | not stored; derived `data/map/streets.json.gz` (1.2 MB) | City of Chicago Street Center Lines (pr57-gg9e): 56,338 segments with names, CLASS codes (City metadata PDF), node ids | 2D map basemap; future street-network routing |
| portal catalog | `data/portal/catalog.json.gz` (0.4 MB, metadata only) | City of Chicago data portal catalog API: every dataset's name, category, columns and types, last data change, declared update frequency, page views | Data tab; `simchi.portal` client typing and freshness |
| `safety_*` (W4) | `data/raw/mirror/safety/*.csv.gz` (1.6 MB) | City of Chicago data portal, downloaded 2026-11-25, **aggregates only**: crashes per site and year (85ca-t3if, 2018-2025, 877,921 crashes; people u6pd-qa9d reduced to pedestrian/cyclist KA counts per crash), Vision Zero deaths per site and year (gzaz-isa6, **begins 2019-01-03**), crashes per month within 660 ft of cameras and comparison intersections, camera locations (4i42-qv3h, thvf-6diy), violations per camera-month (hhkd-xvj4, spqx-js37; context only), mean daily traffic per counted segment (gc7y-n4xa, before 2025) | crash safety layer and its pre-registered test |
| `commitments` | `data/commitments.toml` | public commitments with quote, source URL (and PDF page), metric, measurement and source data; statuses are computed, never typed | promised vs delivered (W5) |
| `frequent_network` | `data/frequent_network.toml` | CTA Frequent Network standard, 24 routes and join dates, transcribed from transitchicago.com pages read 2026-11-23 (one phase's exact date not found: recorded as a window) | Frequent Network checks (W2, W5) |
| `w9_explore_*` | `data/raw/mirror/w9/explore_*.csv.gz` (8.5 MB) | City of Chicago data portal, explore lane (2018-2023), **aggregates only**: merged street- and alley-light outage windows per block from 311 Service Requests (v6vf-nfxy; types "Street Light Out Complaint", "Alley Light Out Complaint"; completed; requests closed in 2024 or later dropped), and crimes (ijzp-q8t2) per block, date, hour, primary type and indoor/outdoor/other (`data/w9_location_map.csv`, all 193 location descriptions of 2018-2023) on blocks that had an outage. Block = W4 street segment | W9 exploratory note |
| `w9_confirm_*` | `data/raw/mirror/w9/confirm_*.csv.gz` | the same aggregates for 2024-01-01 to 2026-10-31, read through the confirm lane after the W9 pre-registration | W9 test |
| landmarks | `data/reference/landmarks.json` | 5 tallest buildings: name, height, coordinates | viewer only; copied from the v0.1 export (which cites Wikipedia, 2026-10-14), not re-verified |

## Method break in CTA ridership (2025-01-01)

CTA restated its ridership back to 2025-01-01 (City of Chicago data portal note "Changes to CTA
Ridership Datasets - 3/20/2026", https://data.cityofchicago.org/stories/s/dw8r-nrdk, read
2026-11-23): recorded counts from the new cash fareboxes replaced estimates, an automatic
passenger counter (APC) factoring process replaced video-based factoring, and underpaid rail
rides were added at station level. CTA's stated effect on the 2025 totals: bus 184.0m to
199.6m rides (+8.5%), rail 135.2m to 138.4m (+2.4%). Values from 2024 and earlier use the old
method. **Never compare ridership before 2025-01-01 with later ridership**: the validation trains
on 2025 and tests on 2026, the viewer marks the break on every ridership chart, and no
year-over-year figure is shown when its earlier window starts before the break.

Checked on 2026-11-23: the two mirrors equal what the portal serves after the restatement
(2025 and Jan-Aug 2026 ride sums and row counts identical for both datasets). The bus mirror's
2025 sum, 198.59m, matches CTA's restated bus total (199.6m) and not the original one (184.0m).
The 'L' station-entry sum, 117.49m, matches neither the original (135.2m) nor the restated
(138.4m) rail total; station entries are a different count from CTA's system rail rides, and the
difference is not explained by the published note.

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

The portal's datasets used here (community areas, CPD records, CTA ridership, traffic crashes,
Vision Zero fatalities, camera locations and violations, traffic counts) are published
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
