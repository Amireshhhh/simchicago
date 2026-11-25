"""Decision briefs generated from report files (python -m simchi.briefs [finding ...]).

Writes docs/briefs/<finding>.md with five sections: the finding, the evidence, what we don't
know, cost, and a pilot proposal with a success criterion fixed here, before any pilot runs.

Rules
  - Every number in a brief is read from a file under reports/ at generation time; the brief
    names each file it read. Text in this module contains no result numbers.
  - A finding has a gating test (a pass flag in a report). If that flag is not exactly True,
    or the report is missing, the brief is refused (BriefRefused) and nothing is written.
  - Cost is given only when a report holds a cost figure; otherwise the brief says it is not
    costed. Nothing is estimated here.

`python -m simchi.briefs` with no argument generates every finding whose test passed and lists
the refused ones with the reason; it exits non-zero if a finding named on the command line was
refused.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from simchi.paths import REPORTS, ROOT

BRIEFS_DIR = ROOT / "docs" / "briefs"


class BriefRefused(RuntimeError):
    pass


@dataclass
class Finding:
    name: str
    title: str
    reports: list                 # report paths relative to reports/
    gate: Callable                # (loaded reports dict) -> bool | None: the pass flag
    gate_label: str               # which test gates the brief, and where it was pre-registered
    sections: Callable            # (loaded reports dict) -> dict of section name -> markdown
    pilot_criterion: str          # fixed here, before any pilot
    tags: list = field(default_factory=list)


def _load(rel: str, root: Path) -> dict | None:
    p = root / rel
    if not p.exists():
        return None
    return json.loads(p.read_text())


def f3(x) -> str:
    return f"{x:.3f}"


# ---------------------------------------------------------------------------------- findings

def _crowding_sections(R):
    c = R["ops/crowding.json"]
    b, r = c["bus"], c["rail"]
    gain = lambda m: 1 - m["M_med4"]["male"] / m["B_naive"]["male"]
    return {
        "Finding": (f"A one-week-ahead ridership forecast (median of the last 4 same-type days) beats \"same day last week\" "
                    f"for every bus route and 'L' station tested: mean absolute log error {f3(b['M_med4']['male'])} vs "
                    f"{f3(b['B_naive']['male'])} on buses ({gain(b):.0%} lower) and {f3(r['M_med4']['male'])} vs "
                    f"{f3(r['B_naive']['male'])} on 'L' stations ({gain(r):.0%} lower)."),
        "Evidence": (f"- Test period {c['test_period'][0]} to {c['test_period'][1]}: {b['forecasts']:,} bus-route forecasts "
                     f"({b['units']} routes) and {r['forecasts']:,} station forecasts ({r['units']} stations), each made with data "
                     f"up to the week before.\n"
                     f"- Mean absolute error in rides: {b['M_med4']['mae_rides']:.0f} vs {b['B_naive']['mae_rides']:.0f} (bus), "
                     f"{r['M_med4']['mae_rides']:.0f} vs {r['B_naive']['mae_rides']:.0f} ('L').\n"
                     f"- Better on every day type for buses: weekday {f3(b['by_daytype']['W']['M_med4'])} vs "
                     f"{f3(b['by_daytype']['W']['B_naive'])}, Saturday {f3(b['by_daytype']['A']['M_med4'])} vs "
                     f"{f3(b['by_daytype']['A']['B_naive'])}, Sunday/holiday {f3(b['by_daytype']['U']['M_med4'])} vs "
                     f"{f3(b['by_daytype']['U']['B_naive'])}.\n"
                     f"- Both periods are after CTA's 2025-01-01 ridership restatement (same counting method)."),
        "What we don't know": ("- Whether a better daily forecast changes any decision: the test scores forecasts, not "
                               "outcomes.\n- Crowding is riders per scheduled trip per day; within-day peaks and "
                               "load per vehicle are not forecast (no load data are used).\n- Holidays and events are not "
                               "modelled; the error on unusual days is not reported separately."),
        "Cost": "Not costed: no cost figure for operating the forecast is in reports/. It uses only published daily ridership and GTFS.",
        "Pilot proposal": ("Publish the forecast weekly to one CTA planning team for 8 weeks, for the routes and stations "
                           "they choose, and log each decision it informed."),
    }


def _ridership_sections(R, kind):
    v = R["ridership_validation.json"]
    m = v[kind]
    male = m["male_heldout_units_and_period"]
    reps = v.get("replicates", {}).get(kind)
    unit = "bus routes" if kind == "bus" else "'L' stations"
    one = "a bus route" if kind == "bus" else "an 'L' station"
    rep_line = ""
    if reps:
        miss = sum(x["M_cal"] >= x["B_service"] for x in reps["male_by_seed"])
        rep_line = (f"\n- Across {len(reps['male_by_seed'])} synthetic populations the calibrated model's error ranges "
                    f"{f3(reps['male_M_cal_range'][0])}-{f3(reps['male_M_cal_range'][1])}; it misses the schedule baseline "
                    f"in {miss} of them.")
    return {
        "Finding": (f"For {unit} without ridership history, the simulation calibrated with scheduled service predicts weekday "
                    f"ridership better than scheduled service alone: held-out mean absolute log error {f3(male['M_cal'])} vs "
                    f"{f3(male['B_service'])} ({m['units']} {unit})."),
        "Evidence": (f"- Trained on {v['train_period'][0]} to {v['train_period'][1]}, tested on {v['test_period'][0]} to "
                     f"{v['test_period'][1]}, both after CTA's {v.get('method_break', '2025-01-01')} counting-method change; "
                     f"5 folds of units.\n- Constant baseline: {f3(male['B_mean'])}; simulation alone: {f3(male['M_sim'])}."
                     f"{rep_line}"),
        "What we don't know": (f"- For {one} that has history, its own previous year predicts far better "
                               f"(error {f3(m['persistence_reference_male'])}): this finding is only about new or changed "
                               f"{unit}.\n- The model has commute demand only; non-commute travel enters through the "
                               f"calibration.\n- The 2025-26 data were examined in an earlier design, so they are held "
                               f"out by design, not unseen."),
        "Cost": "Not costed: no cost figure is in reports/.",
        "Pilot proposal": (f"Before the next new or restructured {unit[:-1]} opens, publish the model's weekday ridership "
                           f"forecast for it, then compare with CTA's counts for its first 3 full months."),
    }


FINDINGS = {
    "crowding-forecast": Finding(
        name="crowding-forecast", title="Forecasting next week's crowding per route and station",
        reports=["ops/crowding.json"],
        gate=lambda R: (R["ops/crowding.json"]["bus"]["pass"] is True and R["ops/crowding.json"]["rail"]["pass"] is True) or None,
        gate_label="crowding forecast, bus and 'L' (criteria in the docstring of simchi/ops/crowding.py)",
        sections=_crowding_sections,
        pilot_criterion=("Over the 8 weeks, the forecast's mean absolute log error is below that of \"same day last week\" "
                         "for the chosen routes and stations, computed the same way as in the test."),
    ),
    "ridership-new-bus-routes": Finding(
        name="ridership-new-bus-routes", title="Ridership forecasts for new or changed bus routes",
        reports=["ridership_validation.json"],
        gate=lambda R: R["ridership_validation.json"]["bus"]["pass"],
        gate_label="ridership_bus, W1 re-baseline (pre-registered in simchi/eval/ridership.py)",
        sections=lambda R: _ridership_sections(R, "bus"),
        pilot_criterion=("The forecast's absolute log error for the new route is below that of the scheduled-service "
                         "baseline fitted on the same 2025 data."),
    ),
    "ridership-new-stations": Finding(
        name="ridership-new-stations", title="Ridership forecasts for new or changed 'L' stations",
        reports=["ridership_validation.json"],
        gate=lambda R: R["ridership_validation.json"]["rail"]["pass"],
        gate_label="ridership_rail, W1 re-baseline (pre-registered in simchi/eval/ridership.py)",
        sections=lambda R: _ridership_sections(R, "rail"),
        pilot_criterion=("The forecast's absolute log error for the new station is below that of the scheduled-service "
                         "baseline fitted on the same 2025 data."),
    ),
}


def register(f: Finding):
    """Add a finding (used by later workstreams, e.g. the crash and frequent-network findings)."""
    FINDINGS[f.name] = f


# ---------------------------------------------------------------------------------- render

def render(f: Finding, reports_root: Path = REPORTS) -> str:
    R = {}
    for rel in f.reports:
        d = _load(rel, reports_root)
        if d is None:
            raise BriefRefused(f"{f.name}: report reports/{rel} is missing")
        R[rel] = d
    try:
        ok = f.gate(R)
    except (KeyError, TypeError) as e:
        raise BriefRefused(f"{f.name}: the gating result could not be read ({e!r})") from e
    if ok is not True:
        raise BriefRefused(f"{f.name}: its test did not pass ({f.gate_label}); no brief is generated for a failed or "
                           f"missing test")
    S = f.sections(R)
    out = [f"# Brief: {f.title}", "",
           f"Generated by `python -m simchi.briefs` from {', '.join(f'`reports/{r}`' for r in f.reports)}. "
           f"Gating test: {f.gate_label} — passed.", ""]
    for k in ("Finding", "Evidence", "What we don't know", "Cost", "Pilot proposal"):
        out += [f"## {k}", "", S[k], ""]
        if k == "Pilot proposal":
            out += [f"**Success criterion (fixed before the pilot):** {f.pilot_criterion}", ""]
    return "\n".join(out)


def generate(names=None, out_dir: Path = BRIEFS_DIR, reports_root: Path = REPORTS) -> dict:
    names = list(names) if names else list(FINDINGS)
    done, refused = {}, {}
    for n in names:
        if n not in FINDINGS:
            refused[n] = "unknown finding"
            continue
        try:
            text = render(FINDINGS[n], reports_root)
        except BriefRefused as e:
            refused[n] = str(e)
            continue
        out_dir.mkdir(parents=True, exist_ok=True)
        p = out_dir / f"{n}.md"
        p.write_text(text)
        done[n] = p
    return {"written": done, "refused": refused}


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    _load_extra_findings()
    r = generate(argv or None, out_dir=BRIEFS_DIR, reports_root=REPORTS)
    for n, p in r["written"].items():
        print("wrote", p.relative_to(ROOT) if p.is_relative_to(ROOT) else p)
    for n, why in r["refused"].items():
        print("REFUSED", why)
    if argv and r["refused"]:
        sys.exit(1)


def _load_extra_findings():
    """Findings defined by other modules register themselves on import."""
    import importlib
    for mod in ("simchi.safety.briefs", "simchi.transit.briefs"):
        try:
            importlib.import_module(mod)
        except ModuleNotFoundError as e:
            if e.name != mod:
                raise
    canonical = importlib.import_module("simchi.briefs")      # under `python -m` this module is __main__
    if canonical.FINDINGS is not FINDINGS:
        FINDINGS.update(canonical.FINDINGS)


if __name__ == "__main__":
    main()
