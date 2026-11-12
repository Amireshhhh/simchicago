"""The workflows must match the request budget in docs/CTA_TERMS.md and must not race."""

import re
from pathlib import Path

from simchi.transit import live

WF = Path(__file__).resolve().parent.parent / ".github" / "workflows"


def test_live_schedule_and_polling_match_the_budget():
    y = (WF / "live.yml").read_text()
    cron = re.search(r'cron:\s*"([^"]+)"', y).group(1)
    assert cron.split()[0].endswith("/5")                       # every 5 minutes at most: <= 288 runs/day
    assert "--polls 3 --interval 60" in y
    assert live.REQUEST_CAP == {"bus": 60, "train": 36}
    # worst case at the cap stays under 50% of the documented limits (100,000 bus; 50,000 train)
    assert 288 * live.REQUEST_CAP["bus"] <= 0.5 * 100_000
    assert 288 * live.REQUEST_CAP["train"] <= 0.5 * 50_000
    # normal use: 13 bus requests (124 routes / 10) and at most 8 train requests per poll
    assert 288 * 3 * 13 <= 288 * live.REQUEST_CAP["bus"] and 288 * 3 * 8 <= 288 * live.REQUEST_CAP["train"]


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
