"""Promised vs delivered: public commitments and their computed status
(python -m simchi.commitments -> reports/commitments/status.json).

PRE-REGISTERED STATUS RULES, W5 (committed as "W5 pre-registration" before any status was computed)

Commitments live in data/commitments.toml: id, agency, the commitment as published (quote),
source URL, metric, how it is measured, and the dataset or report it is measured from. A status
is never typed into that file; this module computes it with the rule named by the commitment's
`rule`, and writes the inputs it used next to the result.

Statuses: "met", "not met", "missed", "on track", "insufficient data", "not measurable".

Rules
  frequent_scheduled   CTA's scheduled service (GTFS extract data/transit/service.json, its
      reference weekday, Saturday and Sunday) for the Frequent Network routes in the network by the
      feed's reference date (data/frequent_network.toml, effective_by). Unit: route x direction x
      day type x hour inside the window (weekdays 6-20 h start hours, weekends 9-20 h). A unit
      meets the standard if its scheduled trips that hour are >= 60 / headway_max (6 trips for 10
      min). Status "met" if every unit meets it, else "not met"; the share of units meeting it is
      reported either way. Trips are counted by the hour of first departure of each trip.
  frequent_delivered   Delivered service from the polling archive (W2 report
      reports/reliability/frequent_network.json). "insufficient data" until that report says its
      pre-registered minimum (8 weeks, per-route coverage threshold) is reached; then "met" if
      every eligible route-hour's observed headway meets the standard, else "not met", with the
      share reported.
  zero_by_year         A goal of zero (deaths or serious injuries) in a target year. Count in the
      target year so far from the named dataset. Count > 0: "missed" (a later month cannot undo it;
      the year-to-date count and the last date in the data are reported). Count = 0 and the year is
      complete in the data: "met"; count = 0 and the year is not complete: "on track".
  reduction_vs_baseline  A percentage reduction by a year. Needs a baseline year stated in the
      source; if the source states none, "not measurable" (no baseline is chosen here). With a
      baseline: "met" if the target-year count <= (1 - reduction) x baseline count, else "not met".
  needs_unmirrored_data  The commitment's metric needs data not in this repository (named in
      `missing`): "not measurable" until it is mirrored.

Every status carries the date it was computed (last checked). Corrections to commitments (a
quote, a source, a rule) are appended to the [[correction]] log in data/commitments.toml with a
date and reason, and shown in the viewer; past entries are never edited.
"""
