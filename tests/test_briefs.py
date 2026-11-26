"""simchi.briefs on constructed reports: numbers come from the report files, a failed or missing
test refuses the brief, and nothing is written for a refused brief."""

import json

import pytest

from simchi import briefs as B


def _crowding(tmp, bus_pass=True):
    def mode(m, n, u, ok):
        return {"forecasts": n, "units": u, "pass": ok,
                "B_naive": {"male": 0.2, "mae_rides": 500.0}, "M_med4": {"male": m, "mae_rides": 400.0},
                "by_daytype": {k: {"B_naive": 0.2, "M_med4": m} for k in "WAU"}}
    d = {"design": "x", "test_period": ["2026-01-01", "2026-08-31"],
         "bus": mode(0.15, 1234, 10, bus_pass), "rail": mode(0.1, 999, 7, True)}
    (tmp / "ops").mkdir(parents=True, exist_ok=True)
    (tmp / "ops" / "crowding.json").write_text(json.dumps(d))


def test_brief_numbers_come_from_the_report(tmp_path):
    _crowding(tmp_path / "reports")
    r = B.generate(["crowding-forecast"], out_dir=tmp_path / "briefs", reports_root=tmp_path / "reports")
    assert not r["refused"]
    text = (tmp_path / "briefs" / "crowding-forecast.md").read_text()
    assert "0.150 vs 0.200 on buses (25% lower)" in text          # 1 - 0.15 / 0.2 = 25%
    assert "0.100 vs 0.200 on 'L' stations (50% lower)" in text
    assert "1,234 bus-route forecasts" in text and "999 station forecasts" in text
    for h in ("## Finding", "## Evidence", "## What we don't know", "## Cost", "## Pilot proposal", "Success criterion (fixed before the pilot)"):
        assert h in text


def test_failed_test_is_refused_and_nothing_written(tmp_path):
    _crowding(tmp_path / "reports", bus_pass=False)
    r = B.generate(["crowding-forecast"], out_dir=tmp_path / "briefs", reports_root=tmp_path / "reports")
    assert "crowding-forecast" in r["refused"] and "did not pass" in r["refused"]["crowding-forecast"]
    assert not (tmp_path / "briefs" / "crowding-forecast.md").exists()


def test_missing_report_is_refused(tmp_path):
    with pytest.raises(B.BriefRefused, match="missing"):
        B.render(B.FINDINGS["crowding-forecast"], tmp_path)


def test_pass_flag_must_be_exactly_true(tmp_path):
    d = {"bus": {"pass": 1}}
    (tmp_path / "ridership_validation.json").write_text(json.dumps(d))
    with pytest.raises(B.BriefRefused):
        B.render(B.FINDINGS["ridership-new-bus-routes"], tmp_path)


def test_cli_exits_nonzero_when_a_named_brief_is_refused(tmp_path, monkeypatch):
    monkeypatch.setattr(B, "REPORTS", tmp_path)
    monkeypatch.setattr(B, "BRIEFS_DIR", tmp_path / "briefs")
    with pytest.raises(SystemExit):
        B.main(["nonexistent-finding"])
    _crowding(tmp_path, bus_pass=False)
    with pytest.raises(SystemExit):
        B.main(["crowding-forecast"])
    assert not (tmp_path / "briefs").exists()
    _crowding(tmp_path, bus_pass=True)
    B.main(["crowding-forecast"])
    assert (tmp_path / "briefs" / "crowding-forecast.md").exists()


def test_cli_sees_findings_registered_by_other_modules_and_refuses_failed_crash_ranking(tmp_path):
    import subprocess
    import sys
    rep = tmp_path / "safety"
    rep.mkdir()
    (rep / "crash_ranking.json").write_text(json.dumps({"test": {"pass": False}}))
    code = (f"import simchi.briefs as B, pathlib; B.REPORTS = pathlib.Path({str(tmp_path)!r}); "
            f"B.BRIEFS_DIR = pathlib.Path({str(tmp_path / 'out')!r}); B.main(['crash-ranking'])")
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert r.returncode == 1 and "did not pass" in r.stdout and "unknown" not in r.stdout
    assert not (tmp_path / "out").exists()


def _measured(tmp, years=True):
    m = tmp / "m.json"
    m.write_text(json.dumps({"value": 0.25, "years": [{"y": 2020, "v": 0.2}] if years else []}))
    return B.Finding(name="m", title="A measured share", reports=["m.json"], gate=lambda R: bool(R["m.json"]["years"]),
                     gate_label="constructed checks", pilot_criterion="", kind="measured",
                     sections=lambda R: {"Measurement": f"Share {R['m.json']['value']:.0%}.",
                                         "Robustness": "| year | v |\n|---|---|\n" + "\n".join(f"| {y['y']} | {y['v']:.0%} |" for y in R["m.json"]["years"]),
                                         "What we don't know": "- Constructed."})


def test_measured_fact_brief_has_its_own_form_and_not_causal_line(tmp_path):
    text = B.render(_measured(tmp_path), tmp_path)
    assert text.startswith("# Brief (measured fact): A measured share")
    assert "Descriptive, not causal." in text and "Share 25%." in text and "| 2020 | 20% |" in text
    assert "Pilot proposal" not in text and "Success criterion" not in text


def test_measured_fact_without_robustness_is_refused(tmp_path):
    with pytest.raises(B.BriefRefused, match="not available"):
        B.render(_measured(tmp_path, years=False), tmp_path)


def test_exploratory_reports_never_go_into_briefs(tmp_path):
    f = _measured(tmp_path)
    f.reports = ["explore/m.json"]
    with pytest.raises(B.BriefRefused, match="exploratory"):
        B.render(f, tmp_path)
