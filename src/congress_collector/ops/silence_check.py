"""Alert via Telegram if the `collect` workflow hasn't succeeded recently.

Run daily by .github/workflows/silence-check.yml. Checks the GitHub
Actions run history directly rather than the `scrape_runs` table, since
this needs to keep working even before T6-T11 make the collector write
anything there.
"""

import os
import sys
from datetime import UTC, datetime, timedelta

import httpx

from congress_collector.notify.telegram import send_message

SILENCE_THRESHOLD = timedelta(hours=24)


def is_silent(last_run_at: datetime | None, now: datetime, threshold: timedelta) -> bool:
    if last_run_at is None:
        return True
    return (now - last_run_at) > threshold


def _latest_successful_run_at(repo: str, token: str) -> datetime | None:
    response = httpx.get(
        f"https://api.github.com/repos/{repo}/actions/workflows/collect.yml/runs",
        params={"status": "success", "per_page": 1},
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
        },
        timeout=15.0,
    )
    response.raise_for_status()
    runs = response.json()["workflow_runs"]
    if not runs:
        return None
    return datetime.fromisoformat(runs[0]["updated_at"].replace("Z", "+00:00"))


def main() -> None:
    repo = os.environ["GITHUB_REPOSITORY"]
    token = os.environ["GITHUB_TOKEN"]

    last_run_at = _latest_successful_run_at(repo, token)
    now = datetime.now(UTC)

    if not is_silent(last_run_at, now, SILENCE_THRESHOLD):
        return

    if last_run_at is None:
        detail = "no successful `collect` run has ever completed"
    else:
        age_hours = (now - last_run_at).total_seconds() / 3600
        detail = f"no successful `collect` run in {age_hours:.1f}h (threshold: 24h)"

    send_message(
        f"Collector silence alert: {detail}. Check the external cron and GitHub Actions.",
        category="system",
    )
    sys.exit(1)


if __name__ == "__main__":
    main()
