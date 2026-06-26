"""Facilities feature — booking links + live library room availability.

Two parts:
  • Links — a tidy index of every SUTD resource/facility booking portal
    (source of truth: ``facilities.md`` at the repo root).
  • Library — the earliest *upcoming* availability today for the four library
    discussion rooms (DRs), scraped server-side from the public availability
    grid at https://mylibrary.sutd.edu.sg/availability .

The library site is an EBSCO Stacks (Drupal) app. Its ``/availability`` page
renders a server-side grid: one row per bookable room, 48 half-hour columns
(12 AM … 11:30 PM), each cell tagged ``available-slot`` or ``unavailable-slot``.
We align cells to the header times by index and pick the first free slot at or
after "now" (Singapore time). Changing the *date* on that page is an AJAX POST
(form token + build id), so we only read today; for other days we link out.
"""

import datetime
import html
import re
from zoneinfo import ZoneInfo

import httpx

SGT = ZoneInfo("Asia/Singapore")

LIBRARY_AVAILABILITY_URL = "https://mylibrary.sutd.edu.sg/availability"

# ── Booking links (mirrors facilities.md) ─────────────────────────────
# (emoji, name, what you can book, url)
RESOURCES = [
    (
        "🏠",
        "Housing Portal",
        "group study rooms, recreation room, meeting room",
        "https://hms.sutd.edu.sg/StarRezPortalX/Login?returnUrl=%2FStarRezPortalX%2F4A537E19%2F14%2F30%2FFacilities-Request_Resource%3FUrlToken%3DF407F1E2&isContact=False",
    ),
    (
        "🎸",
        "Jam Room",
        "music practice room",
        "https://outlook.office.com/bookwithme/user/f318cb771d874f098830e53c55c0e968%40sso.sutd.edu.sg?anonymous&ismsaljsauthenabled=true",
    ),
    (
        "📚",
        "Library",
        "discussion rooms & self-recording studio",
        LIBRARY_AVAILABILITY_URL,
    ),
    (
        "🛠️",
        "Fabrication Lab",
        "fab lab equipment & benches",
        "https://fabricationlab.sutd.edu.sg/fablabbooking/Web/index.php",
    ),
]


# ── Room directory (name ⇄ code lookup) ───────────────────────────────
# SUTD room codes read "building.floor + room" — e.g. 1.408 = Building 1,
# Level 4, room 08. Kept as an ordered list (not a dict) because the source has
# genuine duplicate codes (1.313 is both Think Tank 5 and Cohort Class 1; the
# lecture theatres carry an LT* alias alongside their numeric code).
ROOM_LIST: list[tuple[str, str]] = [
    ("1.308", "Think Tank 1"), ("1.309", "Think Tank 2"), ("1.310", "Think Tank 3"),
    ("1.312", "Think Tank 4"), ("1.313", "Think Tank 5"), ("1.408", "Think Tank 6"),
    ("1.409", "Think Tank 7"), ("1.410", "Think Tank 8"), ("1.415", "Think Tank 9"),
    ("1.416", "Think Tank 10"), ("1.503", "Think Tank 11"), ("1.506", "Think Tank 12"),
    ("1.508", "Think Tank 13"), ("1.509", "Think Tank 14"), ("1.510", "Think Tank 15"),
    ("2.201", "Think Tank 16"), ("2.202", "Think Tank 17"), ("2.203", "Think Tank 18"),
    ("2.304", "Think Tank 19"), ("2.305", "Think Tank 20"), ("2.310", "Think Tank 21"),
    ("2.311", "Think Tank 22"), ("2.413", "Think Tank 23"), ("2.503", "Think Tank 24"),
    ("2.504", "Think Tank 25"), ("2.514", "Think Tank 26"), ("1.603", "Think Tank 27 & 28"),
    ("1.313", "Cohort Class 1"), ("1.314", "Cohort Class 2"), ("1.413", "Cohort Class 3"),
    ("1.414", "Cohort Class 4"), ("1.513", "Cohort Class 5"), ("1.514", "Cohort Class 6"),
    ("1.608", "Cohort Class 7"), ("1.609", "Cohort Class 8"), ("2.307", "Cohort Class 9"),
    ("2.308", "Cohort Class 10"), ("2.405", "Cohort Class 11"), ("2.406", "Cohort Class 12"),
    ("2.506", "Cohort Class 13"), ("2.507", "Cohort Class 14"), ("2.606", "Cohort Class 15"),
    ("2.607", "Cohort Class 16"), ("2.101", "Auditorium"),
    ("LT1", "Albert Hong Lecture Theatre 1"), ("1.102", "Albert Hong Lecture Theatre 1"),
    ("1.203", "Lecture Theatre 2"), ("2.403", "Lecture Theatre 3"),
    ("2.404", "Lecture Theatre 4"), ("2.505", "Lecture Theatre 5"),
]

# Abbreviation expansions so "tt6", "lt3", "cc9" resolve like the full names.
_ABBR = (
    (re.compile(r"\btt\s*(\d+)", re.I), r"think tank \1"),
    (re.compile(r"\blt\s*(\d+)", re.I), r"lecture theatre \1"),
    (re.compile(r"\bcc\s*(\d+)", re.I), r"cohort class \1"),
)


def _norm(s: str) -> str:
    # Drop punctuation (so "think tank 6?" tokenizes cleanly) but keep "." for
    # codes like 1.408 and "&" for "Think Tank 27 & 28".
    s = re.sub(r"[^a-z0-9.& ]+", " ", s.lower())
    return re.sub(r"\s+", " ", s).strip()


def _expand(s: str) -> str:
    for pat, repl in _ABBR:
        s = pat.sub(repl, s)
    return _norm(s)


def _seq_in(needle: list[str], hay: list[str]) -> bool:
    """True if ``needle`` appears as a consecutive run inside ``hay``.

    Token-level (not substring) so "think tank 6" matches "Think Tank 6" but
    never "Think Tank 16" — the numbers are distinct tokens.
    """
    if not needle or len(needle) > len(hay):
        return False
    return any(hay[i : i + len(needle)] == needle for i in range(len(hay) - len(needle) + 1))


def _describe(code: str) -> str | None:
    """A numeric code "a.xbb" → "Building a, Level x". None for LT* aliases."""
    m = re.match(r"^(\d+)\.(\d)(\d{2})$", code)
    if not m:
        return None
    building, floor, _room = m.groups()
    return f"Building {building}, Level {floor}"


def _location(code: str, name: str) -> str | None:
    """Where a result is. Falls back to another code for the same room name
    (so the LT* alias still resolves via its numeric twin, e.g. LT1 → 1.102)."""
    loc = _describe(code)
    if loc:
        return loc
    for c, n in ROOM_LIST:
        if n == name and _describe(c):
            return _describe(c)
    return None


def find_rooms(query: str) -> list[tuple[str, str]]:
    """Resolve free text to matching ``(code, name)`` rooms.

    Order of attack: exact room code → room name appearing as a run inside the
    query (handles "where is think tank 6?") → broad "all words present" so a
    bare "think tank" lists the options.
    """
    raw = _norm(query)
    if not raw:
        return []

    # A room code, whether the whole query ("1.408") or buried in free text
    # ("where is 1.408?"), wins outright.
    q = _expand(raw).split()
    code_hits = [(c, n) for c, n in ROOM_LIST if c.lower() == raw or c.lower() in q]
    if code_hits:
        return code_hits

    strong = [(c, n) for c, n in ROOM_LIST if _seq_in(n.lower().split(), q)]
    pairs = strong or [
        (c, n) for c, n in ROOM_LIST if all(t in n.lower().split() for t in q)
    ]

    seen, out = set(), []  # one line per room name (collapses LT alias duplicates)
    for c, n in pairs:
        if n in seen:
            continue
        seen.add(n)
        out.append((c, n))
    return out


def room_text(query: str) -> str:
    """Markdown answer for the room finder (button flow + Agnes routing)."""
    results = find_rooms(query)
    asked = query.strip()
    if not results:
        return (
            "🔍 *Room finder*\n\n"
            f"I couldn't find a room matching “{asked}”.\n"
            "Try a name like *Think Tank 6*, a code like *1.408*, or *LT3*."
        )
    if len(results) > 8:
        return (
            f"🔍 *Room finder*\n\n{len(results)} rooms match “{asked}”. "
            "Be more specific — add the number, e.g. *Think Tank 6*."
        )
    lines = ["📍 *Room finder*\n"]
    for code, name in results:
        loc = _location(code, name)
        lines.append(f"*{name}* — `{code}`" + (f"\n   {loc}" if loc else ""))
    lines.append(
        "\n_SUTD codes read building.floor+room — e.g. `1.408` = Building 1, Level 4._"
    )
    return "\n".join(lines)


ROOM_PROMPT = (
    "📍 *Find a room*\n\n"
    "Send me a room name or code and I'll tell you the building & level — "
    "e.g. “Think Tank 6”, “LT3”, or “1.408”."
)


def links_text() -> str:
    lines = ["🏛️ *SUTD Facility Bookings*\n", "Tap a portal to book:\n"]
    for emoji, name, what, url in RESOURCES:
        lines.append(f"{emoji} [{name}]({url})\n   _{what}_")
    lines.append("\n📚 Use *Library rooms* below for live discussion-room availability.")
    return "\n".join(lines)


# ── Library discussion-room availability ──────────────────────────────
def _abbr_to_mins(abbr: str) -> int:
    """'8 AM' / '12:30 PM' (grid header) → minutes since midnight."""
    m = re.match(r"(\d+)(?::(\d+))?\s*(AM|PM)", abbr.strip(), re.I)
    if not m:
        return -1
    hour, minute, mer = int(m.group(1)), int(m.group(2) or 0), m.group(3).upper()
    if mer == "AM":
        hour = 0 if hour == 12 else hour
    else:
        hour = 12 if hour == 12 else hour + 12
    return hour * 60 + minute


def _parse_grid(page: str, now_mins: int) -> list[tuple[str, str | None]]:
    """Parse the availability grid HTML.

    Returns ``[(room_name, earliest_label_or_None), …]`` in page order, where
    the label is the grid's own time text (e.g. '8 AM') of the first free slot
    at or after ``now_mins``. ``None`` means nothing bookable left today.
    """
    thead = page[page.find("<thead"): page.find("</thead>")]
    labels = [html.unescape(a) for a in re.findall(r'time-slot-header" abbr="([^"]+)"', thead)]
    mins = [_abbr_to_mins(a) for a in labels]

    tbody = page[page.find("<tbody"): page.find("</tbody>")]
    rows = re.split(r'(?=<tr data-drupal-selector="edit-grid-wrapper-grid-\d+")', tbody)

    out = []
    for row in rows:
        name_m = re.search(r'aria-label="View details for ([^"]+)"', row)
        if not name_m:
            continue
        name = html.unescape(name_m.group(1))
        cells = re.findall(r'class="(available|unavailable)-slot"', row)
        earliest = None
        for i, state in enumerate(cells):
            if state == "available" and i < len(mins) and mins[i] >= now_mins:
                earliest = labels[i]
                break
        out.append((name, earliest))
    return out


async def library_dr_text() -> str:
    now = datetime.datetime.now(SGT)
    now_mins = now.hour * 60 + now.minute
    header = (
        "📚 *Library Discussion Rooms*\n"
        f"_Earliest free slot today ({now.strftime('%a %d %b')}, "
        f"as of {now.strftime('%H:%M')} SGT)_\n"
    )
    try:
        async with httpx.AsyncClient(timeout=10, follow_redirects=True) as client:
            r = await client.get(LIBRARY_AVAILABILITY_URL)
            r.raise_for_status()
        rooms = _parse_grid(r.text, now_mins)
    except Exception:
        return (
            header
            + "\n⚠️ Couldn't reach the library system right now.\n"
            f"Check directly: {LIBRARY_AVAILABILITY_URL}"
        )

    if not rooms:
        return header + "\n⚠️ No room data found — check the site directly."

    lines = [header]
    for name, earliest in rooms:
        short = name.split(" / ")[0]  # drop the "/ Self-Service…" suffix
        if earliest:
            lines.append(f"🟢 *{short}* — from *{earliest}*")
        else:
            lines.append(f"🔴 *{short}* — fully booked today")
    lines.append(
        "\n_30-min slots. Other days & booking:_\n" f"{LIBRARY_AVAILABILITY_URL}"
    )
    return "\n".join(lines)
