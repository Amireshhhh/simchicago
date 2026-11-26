"""Long train gaps and reported crime at CTA rail locations, W10 (python -m simchi.transit.train_gaps).

PRE-REGISTERED DESIGN, W10 (committed as "W10 pre-registration" before any code read its test data;
it runs once the minimum data exist)

DATA
  Exposure: the derived archive files train_station_headways-<date>.csv.gz (W2 amendment 1: station
  id, line, Train Tracker direction, estimated arrival time, headway, continuous). Only continuous
  headways are used (no polling hole over 150 s between the two arrivals).
  Scheduled headway per station, line, Chicago date and hour: 60 / (scheduled trains of that line
  stopping at the station that hour, both directions, divided by 2), from the GTFS feed in effect on
  that date (trips' stop_times at the station's child stops, by hour of arrival). Train Tracker
  directions are not mapped to GTFS direction ids, so the per-direction scheduled frequency is
  taken as half of both directions together.
  Long gap: a station x line x direction headway longer than 2 x the scheduled headway; a station x
  date x hour is a long-gap hour if any arrival in that hour (Chicago time) ends a long gap, and a
  normal hour if it has at least one continuous headway and none is long. Hours with no continuous
  headway are excluded.
  Outcome: City of Chicago Crimes (ijzp-q8t2, read through the confirm lane, simchi.lanes) with
  location_description exactly one of "CTA STATION", "CTA PLATFORM", "CTA TRAIN", 'CTA "L" TRAIN'
  (the station, platform and train values found in 2018-2023 by the W9 explore lane) and a position
  within 400 ft (121.92 m) of the station's GTFS parent-station point, counted per station x date x
  hour. Stored as aggregates only.

DESIGN
  y(s, t) = b x longgap(s, t) + station x hour-of-week fixed effects + error, over station-hours
  with an exposure label; standard errors clustered by station (CR1), 95% interval with t(G-1).
  The comparison is the same station at the same hour of the week in long-gap vs normal periods.
  PASS: b > 0 and its 95% interval excludes 0.

MINIMUM DATA
  12 weeks: train_station_headways files for at least 84 distinct dates. The archive's first
  station-headway file is for 2026-11-13 (re-derived on 2026-11-26, before its run artifacts left
  retention), so if no later date is missing the minimum is reached with the file for 2027-02-04;
  crime records arrive with a seven-day lag (dataset note: "minus the most recent seven days"), so
  the analysis can first run on 2027-02-11. Each missing date moves both by a day. Until then the
  report states "insufficient data".

LIMITS stated in advance
  Reported crime partly reflects police presence: officers deployed at stations, or more reports
  where staff and cameras are, change the count independently of crime. Long gaps may coincide with
  incidents that both delay trains and draw police (reverse causation within the hour). Arrival times
  are estimated to within half a polling interval. Crime locations are block-level.
"""
