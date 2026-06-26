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
