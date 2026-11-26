"""Corridor-level crash concentration test, W4b (python -m simchi.safety.corridors).

PRE-REGISTERED DESIGN, W4b (committed as "W4b pre-registration" before any code read
location-level crash data dated 2026; W4 in simchi/safety/crashes.py is not modified)

CORRIDORS
  Built from the W4 sites (simchi/safety/sites.py; streets of classes 2, 3, 4, 5, 7; expressways
  1 and 9 excluded as not CPD jurisdiction).
  A corridor is a maximal chain of segments with the same street name joined end to end through
  intersections, split at every intersection where the street crosses or meets an arterial (class
  2) segment of a different name (the arterial grid). Each segment belongs to exactly one corridor.
  Intersections: each belongs to the corridor of its highest-order leg (class order 2, 3, 4, 7, 5;
  ties by street name, then corridor id), so no crash is counted twice. Corridor id: the street name
  and the rank of its first segment (by site id) among that street's corridors.
  Bus-corridor subset: corridors of which at least 50% of the length lies within 20 m of a CTA bus
  route shape (GTFS extract), reported separately (not part of the criterion).

OUTCOME
  KA events as in W4: Vision Zero fatal crashes (deaths in the same minute at the same site are one
  crash) plus crash-table crashes with an incapacitating injury and no fatality, snapped to sites by
  the W4 rule, summed over the corridor's sites.
  Vision Zero is updated monthly; test-period K events come from Vision Zero up to its last
  available crash date at mirror time, and from crash-table crashes with injuries_fatal >= 1 for
  dates after it (both recorded in the report).

PERIODS
  Ranking 2018-01-01 .. 2025-12-31 (Vision Zero begins 2019-01-03, as reported for W4)
  Test    2026-01-01 .. 2026-10-31

RANKINGS (top k = 25, 50, 100 corridors)
  EB      negative binomial (NB2, maximum likelihood) of 2018-2025 corridor KA on: highest street
          class (2, 3, other), log length, log(1 + number of intersections), log of the largest
          traffic count on the corridor (W4 site_adt) with a volume-missing indicator; empirical
          Bayes estimate w mu + (1 - w) y, w = 1 / (1 + alpha mu). Ties: corridor id.
  raw     2018-2025 KA (ties: 2018-2025 crashes of any severity, then corridor id)
  y2025   2025 KA (ties: 2025 crashes of any severity, then corridor id)
  Metric: share of test-period KA events at ranked corridors that fall in a ranking's top k.
  PASS: share(EB) > share(raw) and share(EB) > share(y2025) at top 50.
  Reported, not criteria: the shares at 25 and 100, the same for the bus-corridor subset, the
  number of corridors and their length distribution, the model's coefficients and alpha.

LIMITS stated in advance
  Crash reports for recent months are still being added when mirrored, so the test period's last
  weeks may be undercounted (equally for all rankings). Corridor boundaries follow names in the
  City street centerline file.
"""
