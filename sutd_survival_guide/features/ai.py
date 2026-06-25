"""Minimal OpenAI-compatible client for natural-language parsing.

Talks to Agnes AI's ``/chat/completions`` endpoint (configurable in settings)
with a raw httpx call — no SDK needed. Two jobs:
  • parse_datetime         — free-text due date → a timestamp.
  • parse_reminder_offsets — free-text reminder pref → lead times in minutes.

Everything degrades gracefully: if the token is unset or the call fails/returns
junk, callers get ``None`` and fall back to strict parsing.
"""

import datetime
import json
import logging

import httpx

from settings import AGNES_AI_BASE_URL, AGNES_AI_MODEL, AGNES_AI_TOKEN

logger = logging.getLogger(__name__)

_OUT_FORMAT = "%Y-%m-%d %H:%M"
_PLACEHOLDER = "your_agnes_api_token_here"

# Sanity bounds for reminder lead times: 1 minute … 30 days.
_MIN_OFFSET = 1
_MAX_OFFSET = 30 * 24 * 60


def is_configured() -> bool:
    return bool(AGNES_AI_TOKEN) and AGNES_AI_TOKEN != _PLACEHOLDER


async def _complete(system: str, user: str) -> str | None:
    """Single-turn chat completion. Returns the message content, or None."""
    if not is_configured() or not user.strip():
        return None
    payload = {
        "model": AGNES_AI_MODEL,
        "temperature": 0,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user.strip()},
        ],
    }
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.post(
                f"{AGNES_AI_BASE_URL.rstrip('/')}/chat/completions",
                headers={"Authorization": f"Bearer {AGNES_AI_TOKEN}"},
                json=payload,
            )
            resp.raise_for_status()
            return resp.json()["choices"][0]["message"]["content"].strip()
    except Exception as exc:  # network, auth, schema — all non-fatal here
        logger.warning("Agnes AI call failed: %r", exc)
        return None


async def parse_datetime(text: str, now: datetime.datetime) -> datetime.datetime | None:
    """Resolve free-text ``text`` to a datetime, anchored to ``now``."""
    system = (
        "You convert a student's natural-language due date/time into a single "
        "timestamp. The current local date and time is "
        f"{now.strftime('%Y-%m-%d %H:%M')} ({now.strftime('%A')}); the timezone "
        "is Asia/Singapore. Resolve relative expressions ('tomorrow', 'next "
        "Friday', 'in 3 days', 'tonight', 'end of the month') against that. If "
        "no time of day is given, default to 23:59. Reply with ONLY the result "
        "in the exact format YYYY-MM-DD HH:MM (24-hour, zero-padded). If the "
        "text is not a date/time at all, reply with exactly: NONE"
    )
    content = await _complete(system, text)
    if content is None or content.upper().startswith("NONE"):
        return None
    # Be lenient about wrapping (code fences, a leading line of prose, etc.).
    candidate = content.splitlines()[0].strip().strip("`").strip()
    try:
        return datetime.datetime.strptime(candidate, _OUT_FORMAT)
    except ValueError:
        logger.warning("Agnes AI returned unparseable date: %r", content)
        return None


async def parse_reminder_offsets(text: str) -> list[int] | None:
    """Resolve a free-text reminder preference into lead times (minutes-before).

    'a day before' → [1440]; '1 day and 2 hours before' → [1440, 120].
    Returns a sorted (desc), de-duplicated, bounds-checked list, or None.
    """
    system = (
        "Convert the user's reminder preference into lead times BEFORE a "
        "deadline. Reply with ONLY a JSON array of integers, each being the "
        "number of MINUTES before the deadline to send a reminder. Examples: "
        "'a day before' -> [1440]; '1 day and 2 hours before' -> [1440, 120]; "
        "'30 mins before' -> [30]; 'the day before and an hour before' -> "
        "[1440, 60]; 'a week and a day before' -> [10080, 1440]. If you can't "
        "interpret it, reply with exactly: NONE"
    )
    content = await _complete(system, text)
    if content is None or content.upper().startswith("NONE"):
        return None

    # Pull the first JSON array out of the response.
    start, end = content.find("["), content.rfind("]")
    if start == -1 or end == -1 or end < start:
        logger.warning("Agnes AI returned no offset array: %r", content)
        return None
    try:
        raw = json.loads(content[start : end + 1])
    except Exception:
        logger.warning("Agnes AI returned unparseable offsets: %r", content)
        return None

    cleaned = sorted(
        {
            int(v)
            for v in raw
            if isinstance(v, (int, float)) and _MIN_OFFSET <= int(v) <= _MAX_OFFSET
        },
        reverse=True,
    )
    return cleaned or None
