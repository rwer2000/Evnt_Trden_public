"""Minimal Telegram notifier.

Uses the Bot API directly over HTTP rather than a bot framework: this repo
only ever sends messages (new filings, scrape errors, daily DQ summaries),
it never needs to receive updates or handle commands.
"""

import os
from typing import Literal

import httpx

TELEGRAM_API_URL = "https://api.telegram.org"

Category = Literal["filing", "system"]

_PREFIXES: dict[Category, str] = {
    "filing": "\U0001f4c4",  # new filing
    "system": "⚠️",  # error / data-quality alert
}


def send_message(text: str, category: Category = "system") -> None:
    """Send a message to the configured chat, prefixed by category.

    Reads ``TELEGRAM_BOT_TOKEN`` and ``TELEGRAM_CHAT_ID`` from the
    environment on every call rather than at import time, so tests and
    scripts that don't send messages never need them set.
    """
    token = os.environ["TELEGRAM_BOT_TOKEN"]
    chat_id = os.environ["TELEGRAM_CHAT_ID"]
    prefix = _PREFIXES[category]
    response = httpx.post(
        f"{TELEGRAM_API_URL}/bot{token}/sendMessage",
        json={"chat_id": chat_id, "text": f"{prefix} {text}"},
        timeout=10.0,
    )
    response.raise_for_status()
