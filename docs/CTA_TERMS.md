# CTA data: terms, limits and request budget

Read on **2026-11-12** from the pages below (all fetched that day; quotes are verbatim).
SimChicago is **not affiliated with, endorsed by or sponsored by the Chicago Transit
Authority**.

## Sources read

| Document | URL | Version / date shown |
|---|---|---|
| Developer License Agreement & Terms of Use | https://www.transitchicago.com/developers/terms/ | no date shown |
| Bus Tracker APIs (developer page) | https://www.transitchicago.com/developers/bustracker/ | no date shown |
| Bus Tracker API v3 documentation (PDF) | https://www.transitchicago.com/assets/1/6/cta_Bus_Tracker_API_Developer_Guide_and_Documentation_2025-04-21.pdf | v3.0 / rev. 2025-04-21 |
| Train Tracker APIs (developer page) | https://www.transitchicago.com/developers/traintracker/ | no date shown |
| Train Tracker API documentation (PDF) | https://www.transitchicago.com/assets/1/6/cta_Train_Tracker_API_Developer_Guide_and_Documentation.pdf | v1.46 / rev. 04-Aug-2024 |
| GTFS / Scheduled Service Data | https://www.transitchicago.com/developers/gtfs/ | no date shown |
| GitHub Pages limits | https://docs.github.com/en/pages/getting-started-with-github-pages/github-pages-limits | read 2026-11-12 |
| GitHub Actions schedule event | https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows | read 2026-11-12 |
| GitHub Actions billing | https://docs.github.com/en/billing/concepts/product-billing/github-actions | read 2026-11-12 |

## What the terms say, and what SimChicago does about it

**Purpose.** "CTA grants you a limited, non-exclusive, non-assignable, non-transferable and
revocable license to use, reproduce, distribute, display, process and create derivative works
of CTA Data … for the sole purpose of assisting mass transportation (i.e., bus or rail) riders
or in furtherance of promoting public transportation."
→ SimChicago uses CTA Data to evaluate transit service and reliability. Whether that is "in
furtherance of promoting public transportation" is the repository owner's judgement; it is
recorded here so it can be reviewed.

**No affiliation.** "You and your application must not express or imply any affiliation or
relationship with or sponsorship or endorsement by CTA."
→ The viewer footer, the live panel and the README state that SimChicago is not affiliated
with or endorsed by CTA. No CTA logo or trademark is used in the project name or styling;
"CTA" appears only descriptively, as the source of the data.

**Caching.** "You may cache CTA Data you receive from CTA in order to improve your
application's user experience, but you agree to take reasonable efforts to keep the CTA Data
up to date."
→ Live snapshots are refreshed by a scheduled workflow every 5 minutes (when GitHub runs it);
the viewer shows each snapshot's age and marks snapshots older than 30 minutes as stale and
stops animating them.

**No sale.** "You will not sell, auction or barter any CTA Data separate from your
application." → Nothing is sold.

**Credit (optional).** "you have the option, but not the obligation, to credit CTA. If you
elect to include a credit line, it should read as follows: 'Data provided by Chicago Transit
Authority,' 'Data provided by CTA' or 'Powered by CTA data' or similar". For tracker data:
"CTA Bus Tracker data provided by Chicago Transit Authority" and "CTA Train Tracker data
provided by Chicago Transit Authority" (the logo clauses apply only if a logo is used; none is).
→ SimChicago shows: "Data provided by Chicago Transit Authority (CTA Bus Tracker, CTA Train
Tracker, GTFS)."

**Warranty.** "CTA DATA IS PROVIDED ON AN 'AS IS' AND 'AS AVAILABLE' BASIS."
→ The viewer states that live positions may be missing, delayed or wrong.

**Termination.** "Upon any termination or expiration of this Agreement, you will promptly
delete all CTA Data from your application, computer systems or other storage devices".
→ All CTA Data lives in replaceable places: the derived GTFS extract in `data/transit/`,
workflow artifacts `vehicles-<run id>` (14-day retention), the `live-latest-*` workflow cache
and the published snapshot. Removing them is documented in "Deleting CTA data" below.

**Key confidentiality.** The terms do not contain a clause on key handling. Keys are kept
server-side anyway: they live only in the GitHub Actions secrets `CTA_BUS_KEY` and
`CTA_TRAIN_KEY`, are read from environment variables, are masked in logs, are never written to
any file, and `tests/test_no_secrets.py` fails if anything key-like appears in published output.
The browser never calls a CTA API.

**GTFS.** "The CTA implementation of GTFS is the feed delivered in a ZIP file … plus an HTML
file containing a copy of the license agreement and terms of use". "Only one package is
posted at any given time". The feed is the same CTA Data under the same agreement.
→ The raw zip (~51 MB, replaced by CTA every week or two) is not committed or republished:
publishing it unchanged would not be derived, aggregated or snapshot data, which the project
owner asked to approve first. The repository keeps a compact **derived** extract in
`data/transit/` (routes, stations, simplified shapes, representative patterns, scheduled
service by hour), pinned to the sha256 of the zip it was built from (`data/sources.toml`).
`scripts/fetch_gtfs.py` checks a fresh download against that hash and rebuilds only with
`--refresh`; see `docs/DATASETS.md`.

## Request limits

- Bus Tracker: "By default, the Bus Tracker API has a transaction limit of 100,000*
  transactions/day … *Updated default limit from 50,000 to 100,000 in April 2024" (developer
  page); "By default, one API key can make a maximum of 100,000 requests" (v3 PDF).
- Bus Tracker `getvehicles`: `rt` takes "A maximum of 10 identifiers"; "Bus Tracker data is
  updated about every 30 seconds".
- Train Tracker: the developer page says "The default daily transaction limit for this API is
  50,000 transactions"; the PDF (rev. 04-Aug-2024) says 100,000. **The budget uses the lower
  figure, 50,000.** Both say there is "DoS protection … which may trigger a temporary
  'time-out' if a large number of transactions from a single IP address".
- Train Tracker `ttpositions.aspx`: `rt` is "one or more routes", and error 107 reads
  "Maximum number of rt's per request is 8. No more than 8 routes can be issued per request",
  so one request can cover all 8 lines. The documentation shows only single-route examples and
  no multi-route syntax, so the poller sends one comma-separated request and, if CTA rejects it
  (error 106 or 500), falls back to one request per line; **the budget counts the fallback,
  8 requests per poll**.

## Request budget

Schedule: `live.yml` runs on cron every 5 minutes, so at most **288 runs per day** (GitHub:
"The shortest interval you can run scheduled workflows is once every 5 minutes"; scheduled
runs "can be delayed during periods of high loads … some queued jobs may be dropped", so
the real number is at most 288). Each run takes **3 polls**, 60 s apart.

Requests per poll (worst case, every route in service):

- Bus: 124 bus routes in the GTFS feed ÷ 10 routes per request = **13 requests**. Only routes
  with scheduled trips in the current half-hour (from GTFS) are requested, so night polls use
  fewer.
- Train: **1 request** if the combined request is accepted, **8** in the per-line fallback;
  the table uses 8.

| | Bus Tracker | Train Tracker |
|---|---|---|
| documented daily limit | 100,000 | 50,000 (lower of the two stated) |
| 50% target | 50,000 | 25,000 |
| normal: requests/poll × polls/run × runs/day | 13 × 3 × 288 = **11,232** (11.2%) | 8 × 3 × 288 = **6,912** (13.8%) |
| hard cap per run, incl. retries (code: `REQUEST_CAP`) | 60 | 36 |
| worst case at the cap: cap × 288 | **17,280** (17.3%) | **10,368** (20.7%) |

The worst case is under the 50% target even if every run hits its cap. Retries: at most 2 per
request, with exponential backoff of 2 s then 4 s plus jitter, only after a timeout, HTTP 429
or 5xx; never in a loop. When a run reaches its cap, or CTA returns a limit or key error, the
run stops polling, writes what it has, and exits successfully, so the next run starts fresh.
The measured daily use is reported from workflow logs (each run prints its request counts).

## Deleting CTA data

1. Disable `live.yml`; delete the workflow artifacts named `vehicles-*` and the caches named
   `live-latest-*` (Actions → caches).
2. Delete `data/transit/` (and the GTFS entry in `data/sources.toml`).
3. Redeploy Pages (the deployed site then contains no live snapshot or network layer).
