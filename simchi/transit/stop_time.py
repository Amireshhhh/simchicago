"""Seconds saved per skipped bus stop, measured from the polling archive
(python -m simchi.transit.stop_time). Replaces the assumed 20 s in simchi/service_design.py.

PRE-REGISTERED DESIGN, W3 (committed as "W3 pre-registration" before any archive data were used
for it)

Positions are about 60 s apart, too coarse to time individual stops, so the cost of a stop is
estimated cross-sectionally from segment run times.

SEGMENTS
  Each bus route-direction's representative GTFS shape (simchi.transit.reliability.Schedule) is cut
  into consecutive 400 m segments from its start; a final piece under 200 m is dropped, and so are
  the first and last segment of every shape (terminals, layovers).
  stops     the representative pattern's stops whose projection on the shape falls in the segment
  signals   OpenStreetMap highway=traffic_signals nodes within 20 m of the shape, projected on it,
            falling in the segment (fetched by the W3 job through Overpass; the file's sha256 and
            OSM base timestamp are recorded in the report, the file kept as a release asset)
  length    the segment's length along the shape (m)

RUN TIMES
  For each vehicle in each run, positions along its direction's shape (the archive's direction
  inference) are ordered by time; the time it crosses a point is interpolated linearly between the
  two consecutive observations that bracket it (at most 120 s apart, moving forward). A segment
  traversal is kept when both its start and end crossings are interpolated within the same run;
  run time = end - start, kept if 20 s <= run time <= 1200 s. Hour = Chicago hour of the start.

MODEL
  run_time = b_len x length + b_stop x stops + b_sig x signals + hour fixed effects
             + route fixed effects + error,
  ordinary least squares over all kept traversals; standard errors clustered by route (CR1: the
  G/(G-1) x (n-1)/(n-k) small-sample factor); the 95% interval for b_stop is
  b_stop +- t(G-1, 0.975) x SE, G = number of routes. Reported: b_stop with its interval, b_len,
  b_sig, n traversals, G.
  Minimum data: archive (W2) spanning >= 28 days and >= 30 routes with kept traversals; otherwise
  the report states "insufficient data" and nothing is estimated.

STOP BALANCING RERUN (pass rule fixed now)
  simchi/service_design.py's stop balancing is rerun with stop_saving_s equal to the lower end,
  the estimate and the upper end of the b_stop interval (same 10 synthetic populations, same
  spacing rule). Pass only if the lower end is > 0 and the simulated change in weekday transit trips
  at the lower end has a 95% interval entirely above 0. Otherwise the finding is reported as failed.
"""
