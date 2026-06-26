"""Minimal OpenAI-compatible client for natural-language parsing.

Talks to Agnes AI's ``/chat/completions`` endpoint (configurable in settings)
with a raw httpx call — no SDK needed. Three jobs:
  • route                  — free-text message → which tool + intent (the brain).
  • parse_datetime         — free-text due date → a timestamp.
  • parse_reminder_offsets — free-text reminder pref → lead times in minutes.

Every call is timed and counted in ``features.metrics`` so ``/agnes`` can show
the "cheap + fast" story live. Everything still degrades gracefully: if the
token is unset or the call fails/returns junk, callers get ``None`` and fall
back to buttons / strict parsing.
"""

import datetime
import json
import logging
import time

import httpx

from features import metrics
from settings import AGNES_AI_BASE_URL, AGNES_AI_MODEL, AGNES_AI_TOKEN

logger = logging.getLogger(__name__)

_OUT_FORMAT = "%Y-%m-%d %H:%M"
_PLACEHOLDER = "your_agnes_api_token_here"

# Sanity bounds for reminder lead times: 1 minute … 30 days.
_MIN_OFFSET = 1
_MAX_OFFSET = 30 * 24 * 60


def is_configured() -> bool:
    return bool(AGNES_AI_TOKEN) and AGNES_AI_TOKEN != _PLACEHOLDER


async def _complete(system: str, user: str, *, task: str = "chat") -> str | None:
    """Single-turn chat completion. Returns the message content, or None.

    Records latency + token usage in ``features.metrics`` under ``task`` so the
    /agnes panel can report calls/cost/latency live.
    """
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
    start = time.perf_counter()
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.post(
                f"{AGNES_AI_BASE_URL.rstrip('/')}/chat/completions",
                headers={"Authorization": f"Bearer {AGNES_AI_TOKEN}"},
                json=payload,
            )
            resp.raise_for_status()
            data = resp.json()
        metrics.record(task, (time.perf_counter() - start) * 1000, data.get("usage"))
        return data["choices"][0]["message"]["content"].strip()
    except Exception as exc:  # network, auth, schema — all non-fatal here
        metrics.record(task, (time.perf_counter() - start) * 1000, None, ok=False)
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
    content = await _complete(system, text, task="parse_date")
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

    A single compound duration is ONE reminder summed across its units
    ('3 hours and 21 minutes before' → [201]); only clearly-separate requests
    yield several ('a day before and an hour before' → [1440, 60]).
    Returns a sorted (desc), de-duplicated, bounds-checked list, or None.
    """
    system = (
        "Convert the user's reminder preference into one or more lead times "
        "BEFORE a deadline. Reply with ONLY a JSON array of integers, each the "
        "number of MINUTES before the deadline to send a reminder.\n"
        "Combine vs. separate:\n"
        "- A single duration built from several units is ONE reminder = the "
        "SUM. E.g. '3 hours and 21 minutes before' -> [201]; '1 hour 30 "
        "minutes before' -> [90]; '1 day and 2 hours before' -> [1560].\n"
        "- Produce MULTIPLE numbers only when the user clearly wants separate "
        "reminders (repeating 'before'/'again'/'also', or a list). E.g. 'a day "
        "before and an hour before' -> [1440, 60]; 'remind me 1 week, 1 day, "
        "and 1 hour before' -> [10080, 1440, 60].\n"
        "More: 'a day before' -> [1440]; '30 mins before' -> [30]; '2 hours "
        "before' -> [120]. If you can't interpret it, reply with exactly: NONE"
    )
    content = await _complete(system, text, task="parse_offsets")
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


# ── Routing brain ──────────────────────────────────────────────────────
# Controlled feature → intent vocabulary. The bot's dispatcher (bot._dispatch_
# route) must handle every (feature, intent) pair here. The first intent in each
# list is the safe default if the model returns an unknown one for that feature.
_ROUTES: dict[str, list[str]] = {
    "gym": ["status", "recent", "popular"],
    "deadlines": ["list", "upcoming", "modules", "stats", "add"],
    "train": ["trains", "buses"],
    "facilities": ["links", "library", "room"],
}

_ROUTER_SYSTEM = (
    "You are the router for a SUTD student-helper Telegram bot with four tools. "
    "Classify the user's message into exactly one tool + intent and reply with "
    'ONLY a JSON object: {"feature": ..., "intent": ..., "reply": ...}.\n'
    "Tools and their intents:\n"
    "- gym: status (how busy / current occupancy), recent (recent entries/"
    "exits), popular (best or quiet times to go)\n"
    "- deadlines: list (all pending), upcoming (due soon / this week), modules "
    "(which modules I'm in / share codes), stats (progress / completion rate), "
    "add (create or add an exam, homework, assignment or project)\n"
    "- train: trains (last MRT train times home), buses (live bus arrivals)\n"
    "- facilities: links (booking portals / links for rooms, jam room, fab "
    "lab), library (free library discussion rooms right now), room (WHERE a "
    "room is — its building & level; e.g. “where is Think Tank 6”, “which "
    "floor is LT3”, “1.408”)\n"
    "- none: anything else — greeting, thanks, unrelated, or asking what you "
    "can do.\n"
    "Rules: pick the single best match. Use feature 'none' only when no tool "
    'fits. Set "reply" to "" UNLESS feature is "none", in which case put a '
    "short, friendly one-sentence answer (if they ask what you can do, mention "
    "the four tools: gym crowd, deadlines, last train home, facilities). "
    "Output JSON only — no prose, no code fences."
)


async def route(text: str) -> dict | None:
    """Classify a free-text message → ``{"feature", "intent", "reply"}``.

    ``feature`` is one of ``_ROUTES`` keys or ``"none"`` (not a tool request —
    ``reply`` then carries a short natural answer). Returns ``None`` when Agnes
    is off / unreachable / unparseable, so the caller can fall back to buttons.
    """
    content = await _complete(_ROUTER_SYSTEM, text, task="route")
    if content is None:
        return None
    start, end = content.find("{"), content.rfind("}")
    if start == -1 or end == -1 or end < start:
        logger.warning("Agnes AI route returned no JSON: %r", content)
        return None
    try:
        obj = json.loads(content[start : end + 1])
    except Exception:
        logger.warning("Agnes AI route unparseable: %r", content)
        return None

    feature = str(obj.get("feature", "none")).lower().strip()
    intent = str(obj.get("intent", "")).lower().strip()
    reply = str(obj.get("reply", "")).strip()
    if feature not in _ROUTES:
        feature = "none"
    elif intent not in _ROUTES[feature]:
        intent = _ROUTES[feature][0]  # safe default for that tool
    return {"feature": feature, "intent": intent, "reply": reply}
