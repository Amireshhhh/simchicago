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
