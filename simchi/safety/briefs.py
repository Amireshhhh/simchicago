"""Decision-brief finding for the W4 crash ranking (registered with simchi.briefs on import)."""

from simchi.briefs import Finding, f3, register


def _sections(R):
    r = R["safety/crash_ranking.json"]
    t, s = r["test"], r["test"]["captured_share"]["100"]
    n = t["ka_2025_at_ranked_sites"]
    return {
        "Finding": (f"Ranking street sites by an empirical-Bayes estimate of serious crashes puts {s['EB']:.1%} of the next "
                    f"year's serious crashes in the top 100 sites, against {s['raw']:.1%} for raw counts and {s['y2024']:.1%} for "
                    f"the latest year alone."),
        "Evidence": f"- {int(n):,} serious crashes in {r['test_year']} at {t['sites_ranked']:,} ranked sites; dispersion alpha {f3(t['alpha'])}.",
        "What we don't know": "- Traffic volume is counted at few sites; lanes are not available.",
        "Cost": "Not costed: no cost figure is in reports/.",
        "Pilot proposal": "Treat the top-ranked sites first in a year's safety program and compare their serious crashes with matched sites.",
    }


register(Finding(
    name="crash-ranking", title="Where to treat first: serious-crash sites ranked with empirical Bayes",
    reports=["safety/crash_ranking.json"],
    gate=lambda R: R["safety/crash_ranking.json"]["test"]["pass"],
    gate_label="W4 crash ranking, top-100 share of 2025 serious crashes (pre-registered in simchi/safety/crashes.py)",
    sections=_sections,
    pilot_criterion="Serious crashes at treated sites fall more than at matched untreated sites over two years.",
))


def _concentration_sections(R):
    w4, rb = R["safety/crash_ranking.json"], R["safety/robustness.json"]
    s = w4["test"]["captured_share"]["100"]
    n = w4["test"]["ka_2025_at_ranked_sites"]
    rows = ["| Test year | Top 100 sites, raw count | Top 100, empirical Bayes | Oracle ceiling | Intersections only, raw | Sites with any serious crash |",
            "|---|---|---|---|---|---|"]
    for y in rb["years"]:
        a, i = y["all_sites"], y["intersections"]
        rows.append(f"| {y['test_year']} | {a['raw']:.2%} | {a['EB']:.2%} | {a['oracle']:.2%} | {i['raw']:.2%} | {a['share_of_units_with_any']:.2%} |")
    lo = min(y["all_sites"]["oracle"] for y in rb["years"])
    hi = max(y["all_sites"]["oracle"] for y in rb["years"])
    return {
        "Measurement": (f"Serious traffic crashes (deaths and incapacitating injuries) in Chicago are spread over many street "
                        f"locations. The 100 street sites with the most serious crashes in 2018-2024 held {s['raw']:.2%} of "
                        f"2025's serious crashes ({int(round(s['raw'] * n))} of {int(n):,}), out of "
                        f"{w4['test']['sites_ranked']:,} street sites. Even the 100 sites that turned out to have the most "
                        f"serious crashes in a year held only {lo:.2%}-{hi:.2%} of that year's (2019-2024)."),
        "Robustness": "Same measurement for each year 2019-2024, ranking on all earlier years from 2018 (D):\n\n" + "\n".join(rows),
        "What we don't know": ("- Why crashes are spread this way, and whether treating the worst sites would reduce them: "
                               "nothing here tests an intervention.\n- Traffic volume is counted at few sites, so these are "
                               "counts, not rates per vehicle.\n- Vision Zero records begin in 2019; reporting of recent months "
                               "is still being completed."),
    }


register(Finding(
    name="crash-concentration", title="Serious crashes are spread thinly across Chicago's streets",
    reports=["safety/crash_ranking.json", "safety/robustness.json"],
    gate=lambda R: bool(R["safety/robustness.json"].get("years")) and "captured_share" in R["safety/crash_ranking.json"]["test"],
    gate_label="W4 measurement (simchi/safety/crashes.py) and the pre-registered robustness checks D (simchi/safety/robustness.py)",
    sections=_concentration_sections, pilot_criterion="", kind="measured",
))
