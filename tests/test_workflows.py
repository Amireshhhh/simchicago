"""The workflows must match the request budget in docs/CTA_TERMS.md and must not race."""

import re
from pathlib import Path

from simchi.transit import live

WF = Path(__file__).resolve().parent.parent / ".github" / "workflows"


def test_live_schedule_and_polling_match_the_budget():
    y = (WF / "live.yml").read_text()
    cron = re.search(r'cron:\s*"([^"]+)"', y).group(1)
    assert cron.split()[1] == "*" and cron.split()[0].isdigit()      # hourly restarter: <= 24 runs/day
    assert "--polls 5 --interval 60" in y
    # the run-to-run chain waits until 5 minutes after the run started and never forks
    assert "wait=$(( 300 - elapsed ))" in y and "not chaining" in y and "vars.LIVE_CHAIN != 'off'" in y
    runs = 288 + 24
    assert live.REQUEST_CAP == {"bus": 100, "train": 45}
    # worst case at the cap stays under 50% of the documented limits (100,000 bus; 50,000 train)
    assert runs * live.REQUEST_CAP["bus"] <= 0.5 * 100_000
    assert runs * live.REQUEST_CAP["train"] <= 0.5 * 50_000
    assert 5 * 13 <= live.REQUEST_CAP["bus"] and 5 * 8 <= live.REQUEST_CAP["train"]          # a normal run fits under the cap
    assert runs * 5 * 13 <= 0.5 * 100_000 and runs * 5 * 8 <= 0.5 * 50_000


def test_builds_and_polls_do_not_cancel_each_other():
    """Each workflow queues only behind itself; only the deploy jobs share a group."""
    groups = {}
    for name in ("live.yml", "pages.yml"):
        y = (WF / name).read_text()
        top = re.search(r"^concurrency:\s*\n\s*group: ([\w-]+)\s*\n\s*cancel-in-progress: false", y, re.M)
        assert top, name
        groups[name] = top.group(1)
        assert re.search(r"  deploy:\n(?:    .*\n)*?    concurrency:\n      group: pages-deploy\n      cancel-in-progress: false", y), name
    assert groups["live.yml"] != groups["pages.yml"]


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


def test_archive_workflow_is_append_only_and_makes_no_cta_requests():
    text = (WF / "archive.yml").read_text()
    code = "\n".join(line.split("#")[0] for line in text.splitlines())          # commands, without comments
    assert "CTA_BUS_KEY" not in text and "CTA_TRAIN_KEY" not in text and "ctabustracker" not in text and "lapi.transitchicago" not in text
    assert "--clobber" not in code and "gh release upload" in code
    assert 'tag="history-$y"' in text
    assert "contents: write" in text


def test_raw_positions_are_published_only_with_the_owners_switch():
    code = "\n".join(line.split("#")[0] for line in (WF / "archive.yml").read_text().splitlines())
    ups = [line.strip() for line in code.splitlines() if "gh release upload" in line]
    assert any("stats-" in u and "traversals-" in u and "vehicles-" not in u for u in ups)
    raw = [u for u in ups if "vehicles-" in u]
    assert raw and all(u.startswith('if [ "${ARCHIVE_RAW:-off}" = "on" ]') for u in raw)


def test_archive_never_uploads_a_partial_day_and_throttles():
    text = (WF / "archive.yml").read_text()
    i_skip = text.index('if [ "$incomplete" -eq 1 ]; then echo "SKIPPED')
    i_upload = text.index("gh release upload")
    assert i_skip < i_upload and "incomplete=1" in text and "gh api rate_limit" in text
