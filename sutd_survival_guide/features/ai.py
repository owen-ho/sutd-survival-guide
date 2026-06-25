"""Minimal OpenAI-compatible client for natural-language date parsing.

Talks to Agnes AI's ``/chat/completions`` endpoint (configurable in settings)
with a raw httpx call — no SDK needed. The only thing it does is turn a free-text
due date like "next Friday 2pm" into a concrete timestamp. Everything degrades
gracefully: if the token is unset or the call fails/returns junk, callers get
``None`` and fall back to strict-format parsing.
"""

import datetime
import logging

import httpx

from settings import AGNES_AI_BASE_URL, AGNES_AI_MODEL, AGNES_AI_TOKEN

logger = logging.getLogger(__name__)

_OUT_FORMAT = "%Y-%m-%d %H:%M"
_PLACEHOLDER = "your_agnes_api_token_here"


def is_configured() -> bool:
    return bool(AGNES_AI_TOKEN) and AGNES_AI_TOKEN != _PLACEHOLDER


async def parse_datetime(text: str, now: datetime.datetime) -> datetime.datetime | None:
    """Resolve free-text ``text`` to a datetime, anchored to ``now``.

    Returns ``None`` when AI isn't configured, the text isn't a date, or the
    response can't be parsed — so the caller can fall back or re-prompt.
    """
    if not is_configured() or not text.strip():
        return None

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
    payload = {
        "model": AGNES_AI_MODEL,
        "temperature": 0,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": text.strip()},
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
            content = resp.json()["choices"][0]["message"]["content"].strip()
    except Exception as exc:  # network, auth, schema — all non-fatal here
        logger.warning("Agnes AI date parse failed: %r", exc)
        return None

    if content.upper().startswith("NONE"):
        return None

    # Be lenient about wrapping (code fences, a leading line of prose, etc.).
    candidate = content.splitlines()[0].strip().strip("`").strip()
    try:
        return datetime.datetime.strptime(candidate, _OUT_FORMAT)
    except ValueError:
        logger.warning("Agnes AI returned unparseable date: %r", content)
        return None
