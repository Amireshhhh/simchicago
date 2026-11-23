"""Crash safety layer: where serious crashes concentrate, ranked with empirical Bayes, and a
camera before/after slice (python -m simchi.safety.crashes).

PRE-REGISTERED DESIGN, W4 (fixed in this docstring and committed as "W4 pre-registration"
before any crash, fatality, camera or traffic-count values were downloaded or examined; only the
portal's column metadata had been read).

DATA (City of Chicago data portal, mirrored through simchi.portal.client, pinned by sha256 in
data/sources.toml; only aggregates are stored, never person-level records)
  crashes      85ca-t3if Traffic Crashes - Crashes, crash_date 2018-01-01 .. 2025-12-31
               (citywide reporting starts September 2017, so 2018 is the first full year)
  people       u6pd-qa9d Traffic Crashes - People, aggregated on the portal to counts per crash and
               person type of fatal and incapacitating injuries; context only
  deaths       gzaz-isa6 Vision Zero Chicago Traffic Fatalities: the official death count
  cameras      4i42-qv3h Speed Camera Locations, thvf-6diy Red Light Camera Locations (go-live dates)
  violations   hhkd-xvj4, spqx-js37, aggregated per camera and month; context only, never a layer
  volume       gc7y-n4xa Average Daily Traffic Counts (camera-derived, from 2020-10), mean daily
               count per counted segment over days before 2025-01-01 (training years only)
  streets      data/map/streets.json.gz (Street Center Lines pr57-gg9e, derived extract)
  Lanes: neither the street extract nor the centerline dataset has a lane count, and the crash
  records' lane_cnt exists only where crashes happened (using it would leak the outcome into the
  covariates). Lanes are therefore not in the model; this is reported, not filled in.

SITES
  Street classes 2 (arterial), 3 (collector), 4 (other street), 5 (named alley), 7 (tiered) are
  CPD streets. Classes 1 (expressway) and 9 (ramp) are not CPD's jurisdiction: excluded from the
  ranking and the test, drawn grey on the map, and their crashes reported separately.
  Intersection: a segment end point (coordinates to 5 decimals) shared by >= 3 segment ends; it is
  excluded only if every leg is class 1 or 9. Segment: one feature of the street extract.
  Snapping: a crash (or Vision Zero death) within 30 m of an intersection belongs to it; otherwise
  to the nearest non-river segment within 50 m; otherwise it is unsnapped (counted, reported).
  Distances in a local metric projection (the simulation frame, UTM 16N).

OUTCOME (serious crashes, "KA")
  K events: Vision Zero fatalities grouped into crashes (same crash_date to the minute and the same
            snapped site count as one fatal crash). Vision Zero, not the crash table, is the death
            count.
  A events: crash-table crashes with injuries_incapacitating >= 1 and injuries_fatal = 0.
  KA count of a site in a period = K events + A events snapped to it.

PERIODS
  Ranking (training)  2018-01-01 .. 2024-12-31
  Test                2025-01-01 .. 2025-12-31

MODEL
  Negative binomial (NB2: variance mu + alpha mu^2), fitted by maximum likelihood on every
  ranked site's 2018-2024 KA count (zeros included), with covariates:
    site type (intersection / segment);
    road class: segments by their class (2, 3, 4, other); intersections by the highest-order
      class among their legs, plus the number of legs (3, 4, >= 5);
    log segment length (segments; intersections 0);
    log average daily traffic where a count is snapped (within 30 m of the segment, or the
      largest count on any leg of an intersection), with a "volume missing" indicator.
  Empirical Bayes estimate per site: w = 1 / (1 + alpha mu), EB = w mu + (1 - w) y, with mu the
  model's expected 2018-2024 KA count and y the observed one.

TEST (primary)
  Three rankings of the ranked sites, top 100 each:
    EB      by the EB estimate (ties: site id)
    raw     by the 2018-2024 KA count (ties: 2018-2024 crashes of any severity, then site id)
    y2024   by the 2024 KA count (ties: 2024 crashes of any severity, then site id)
  Metric: share of 2025 KA events at ranked sites that occur at the ranking's top 100 sites.
  Pass: share(EB) > share(raw) and share(EB) > share(y2024).
  Reported, not criteria: the same shares for the top 50 and top 200; unsnapped and expressway
  2025 KA events; the fitted coefficients and alpha.

CAMERA SLICE (descriptive, no pass criterion)
  Cameras (speed and red-light separately) whose go-live date is in 2019-01-01 .. 2024-12-31, so
  12 full months before and after fall inside 2018-2025. Pre = the 12 calendar months before the
  go-live month; post = the 12 months after it (the go-live month itself is excluded).
  Counted: crashes (any severity) and KA crashes from the crash table within 660 ft (201.2 m) of
  the camera.
  Comparison pool: intersections with at least one class-2 leg and no speed or red-light camera
  (of any date) within 805 m (1/2 mile). Each camera is matched, with replacement, to the 3 pool
  intersections whose crash count within 201.2 m in the camera's pre window is closest (ties: site
  id), and those are counted over the camera's own pre and post windows.
  Estimate: ratio of ratios (sum post / sum pre at cameras) / (sum post / sum pre at comparisons),
  for all crashes and for KA, with a 95% interval from 2,000 bootstrap resamples of cameras
  (seed 0). Matching on the pre-period count limits, but does not remove, regression to the mean
  (cameras are sited where crashes were high). Violation counts are shown next to each camera as
  context, never as a separate layer or outcome.
"""
