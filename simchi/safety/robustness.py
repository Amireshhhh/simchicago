"""Robustness of the crash concentration finding, D (python -m simchi.safety.robustness).

PRE-REGISTERED DESCRIPTIVE CHECKS (committed as "D pre-registration" before they were computed;
no pass or fail: these describe how concentrated serious crashes are, they test nothing)

The W4 finding: the top 100 of 76,522 ranked sites held under 5% of 2025's serious (KA) crashes.
These checks ask whether that holds in other years and for other units. Data, sites, outcome and
the NB2/empirical Bayes model are W4's (simchi/safety/crashes.py); 2019-2024 were W4's training
years, so nothing here is out of sample in the sense of an unseen period.

For each test year Y in 2019 .. 2024, rank on all years 2018 .. Y-1 and report, for k = 100:
  all sites          share of year-Y KA events at ranked sites captured by the top k, ranked by
                     (a) empirical Bayes (NB2 refitted on 2018 .. Y-1) and (b) raw count
                     (ties as in W4); this is W4's design moved back in time
  segments per mile  segments only, ranked by KA per mile, (a) EB / length and (b) raw count /
                     length, segments shorter than 100 m excluded (a few metres would make any single
                     crash a huge rate); share of year-Y segment KA events in the top k
  intersections      intersections only, (a) EB and (b) raw count; share of year-Y intersection
                     KA events in the top k
Also reported: the share of ranked units holding any KA event in year Y, and the top-k share an
oracle would reach (the k units with most year-Y KA), as the ceiling.
Output: reports/safety/robustness.json and a table in docs/EVALUATION.md.
"""
