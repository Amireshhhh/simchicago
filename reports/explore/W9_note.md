# W9 exploratory note (EXPLORATORY: explore lane, 2018-2023; not a result, not public, not briefed)

Source: `python -c "from simchi.safety.lights_explore import main; main(['--analyse'])"` →
`reports/explore/w9_explore.json`. Read through the explore lane (`reports/lanes/reads.jsonl`).

**What the data look like.** 350,243 completed street- and alley-light-out requests (2018-12 to
2023, the 311 dataset starts 2018-12-18), 4,725 unsnapped; 1,134 requests
closed in 2024 or later were dropped (their closing date is post-2023 information). Merged into
159,750 outage windows on 40,971 blocks; median window 9 days (10th-90th
percentile 1-111). 1,458,767 crimes, 1,282,567 on blocks that had an outage.

**First look at the design** (same estimator as the planned test, on 2018-2023): night x outage
-0.000056 outdoor crimes per block and band-day, 95% interval
[-0.000165, 0.000052], 39,750 blocks, 287 weeks. Mean outdoor
crimes per block-night: 0.00241 during outages, 0.00237 after repair; per block-day band:
0.00179 and 0.00170. Nothing here is a finding.

**What exploring changed in the confirm design** (all decided before any 2024+ data were read):
1. A request created in the window but closed after it carries information from beyond the window:
   such requests are dropped, and outage windows must end at least one day before the window ends,
   so their after-repair days lie inside it.
2. After-repair days beyond the last day of crime data were counted as zero crimes in a first run:
   panel days are cut at the window's end.
3. The outcome is sparse (about 0.0024 outdoor crimes per block-night), so the interval is wide in
   relative terms; with the explore period's standard error the smallest detectable effect is about
   5% of the after-repair night mean. The confirm window (34 months) is shorter
   than the explore window, so its interval will be wider.
