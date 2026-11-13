"""The workflows must match the request budget in docs/CTA_TERMS.md and must not race."""

import re
from pathlib import Path

from simchi.transit import live

WF = Path(__file__).resolve().parent.parent / ".github" / "workflows"


def test_live_schedule_and_polling_match_the_budget():
    y = (WF / "live.yml").read_text()
    cron = re.search(r'cron:\s*"([^"]+)"', y).group(1)
    assert cron.split()[1] == "*" and cron.split()[0].isdigit()      # hourly restarter: <= 24 runs/day
    assert "--polls 3 --interval 60" in y
    # the run-to-run chain waits until 5 minutes after the run started and never forks
    assert "wait=$(( 300 - elapsed ))" in y and "not chaining" in y and "vars.LIVE_CHAIN != 'off'" in y
    runs = 288 + 24
    assert live.REQUEST_CAP == {"bus": 60, "train": 36}
    # worst case at the cap stays under 50% of the documented limits (100,000 bus; 50,000 train)
    assert runs * live.REQUEST_CAP["bus"] <= 0.5 * 100_000
    assert runs * live.REQUEST_CAP["train"] <= 0.5 * 50_000
    assert runs * 3 * 13 <= runs * live.REQUEST_CAP["bus"] and runs * 3 * 8 <= runs * live.REQUEST_CAP["train"]


def test_workflows_share_a_concurrency_group():
    for name in ("live.yml", "pages.yml"):
        y = (WF / name).read_text()
        assert re.search(r"concurrency:\s*\n\s*group: pages\s*\n\s*cancel-in-progress: false", y), name


def test_keys_only_from_secrets_and_never_echoed():
    y = (WF / "live.yml").read_text()
    assert "secrets.CTA_BUS_KEY" in y and "secrets.CTA_TRAIN_KEY" in y
    for line in y.splitlines():
        if "echo" in line and ("CTA_BUS_KEY" in line or "CTA_TRAIN_KEY" in line):
            assert "::add-mask::" in line, line
    assert "retention-days: 14" in y


def test_pages_workflow_never_sees_cta_keys():
    y = (WF / "pages.yml").read_text()
    assert "CTA_BUS_KEY" not in y and "CTA_TRAIN_KEY" not in y and "{{ secrets." not in y
