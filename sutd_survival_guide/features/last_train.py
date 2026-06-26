"""Last Train Home feature — native rebuild of Gabriel's web app.

Three parts mirror the web app's tabs:
  • Trains — static published last-train times (LTA has no live MRT countdown).
  • Buses  — live arrivals via the arrivelah API (server-side fetch here).
  • Plan   — "can I catch the last train?" calculator (button-driven guided flow).
"""

import datetime
from zoneinfo import ZoneInfo

import httpx
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

# SUTD is in Singapore; the bot may run anywhere, so anchor "now" to SGT.
SGT = ZoneInfo("Asia/Singapore")

# ── Static train data (ported from the web app) ───────────────────────
HOME_STATION = {
    "name": "Upper Changi (EW4 · DT32)",
    "groups": [
        ("East West Line", [("→ Tanah Merah / Pasir Ris", "23:18"), ("→ Expo / Joo Koon", "23:17")]),
        ("Downtown Line", [("→ Expo / Buona Vista", "23:41"), ("→ Bukit Panjang", "23:23")]),
    ],
}
TRANSFER_STATIONS = [
    {"name": "MacPherson (CC10 · DT26)", "groups": [
        ("Circle Line", [("→ Bartley / Dhoby Ghaut", "23:34"), ("→ HarbourFront", "23:45")]),
        ("Downtown Line", [("→ Bukit Panjang", "23:30"), ("→ Expo", "23:50")]),
    ]},
    {"name": "Tampines (EW2 · DT32)", "groups": [
        ("East West Line", [("→ Pasir Ris", "23:52"), ("→ Joo Koon", "00:01")]),
    ]},
    {"name": "Serangoon (NE12 · CC13)", "groups": [
        ("North East Line", [("→ Punggol", "23:27"), ("→ HarbourFront", "23:24")]),
        ("Circle Line", [("→ Bartley", "23:49"), ("→ HarbourFront", "00:00")]),
    ]},
    {"name": "Bishan (NS17 · CC15)", "groups": [
        ("North South Line", [("→ Jurong East / Woodlands", "23:42"), ("→ Marina South Pier", "00:00")]),
        ("Circle Line", [("→ Bartley", "23:49"), ("→ HarbourFront", "00:00")]),
    ]},
]

# ── Bus stops near SUTD (arrivelah live API) ──────────────────────────
BUS_STOPS = [
    {"code": "96449", "name": "Somapah Rd (SUTD)", "walk": "2 min", "highlight": ["20"]},
    {"code": "96041", "name": "Upp Changi Rd East", "walk": "5 min", "highlight": ["2", "5", "24"]},
    {"code": "96049", "name": "Upp Changi Rd East (Opp)", "walk": "5 min", "highlight": ["2", "5", "24"]},
    {"code": "97009", "name": "Changi Business Pk Terminal", "walk": "8 min", "highlight": ["47", "118"]},
]


def _station_block(station: dict) -> str:
    lines = [f"*{station['name']}*"]
    for label, trains in station["groups"]:
        lines.append(f"  _{label}_")
        for direction, last in trains:
            lines.append(f"    {direction} — last {last}")
    return "\n".join(lines)


def trains_text() -> str:
    blocks = [_station_block(HOME_STATION)]
    blocks += [_station_block(s) for s in TRANSFER_STATIONS]
    return (
        "🚆 *Last Train Home*\n_Departure: Upper Changi MRT (~5 min from SUTD gate)_\n\n"
        + "\n\n".join(blocks)
    )


async def buses_text() -> str:
    """Fetch live arrivals server-side and format them."""
    out = ["🚌 *Live Bus Arrivals*\n"]
    async with httpx.AsyncClient(timeout=8) as client:
        for stop in BUS_STOPS:
            out.append(f"*{stop['name']}* (Stop {stop['code']} · {stop['walk']})")
            try:
                r = await client.get(f"https://arrivelah2.busrouter.sg/?id={stop['code']}")
                r.raise_for_status()
                services = r.json().get("services", [])
            except Exception:
                out.append("  ⚠️ Could not load live data\n")
                continue
            if not services:
                out.append("  No buses currently operating\n")
                continue
            hi = [s for s in services if s["no"] in stop["highlight"]]
            rest = [s for s in services if s["no"] not in stop["highlight"]]
            for svc in (hi + rest)[:5]:
                eta = _eta_mins(svc.get("next", {}).get("time"))
                star = "⭐" if svc["no"] in stop["highlight"] else ""
                out.append(f"  {star}{svc['no']}: {eta}")
            out.append("")
    out.append("_Live via arrivelah (LTA DataMall)._")
    return "\n".join(out)


def _eta_mins(iso: str | None) -> str:
    if not iso:
        return "—"
    try:
        diff = (datetime.datetime.fromisoformat(iso) - datetime.datetime.now(
            datetime.timezone.utc).astimezone()).total_seconds() / 60
    except Exception:
        return "—"
    m = round(diff)
    return "Arr" if m <= 0 else f"{m}m"


# ── Plan my trip ──────────────────────────────────────────────────────
# Interactive port of the web app's "Plan Trip" tab. Telegram has no native
# time picker, so the verdict defaults to *now* (SGT) and the user can type a
# planned departure time to ask "can I still catch it if I leave at 11pm?".
# The flow is button-driven:
#   train:plan          → pick where you are   (plan:loc:<loc_idx>)
#   plan:loc:<i>        → pick which station   (plan:res:<loc_idx>:<station_idx>)
#   plan:res:<i>:<j>    → verdict per direction, anchored to now
#   plan:time:<i>:<j>   → prompt for a leave time; the typed reply recomputes
# Selections live in the callback data; the only transient state is the pending
# "waiting for a typed time" flag, handled in bot.py via context.user_data.

# Campus spots → walking minutes to Upper Changi MRT (ported from the web app).
CAMPUS_LOCATIONS = [
    ("⚽ Sports & Rec", 12),
    ("🏛️ Building 1", 9),
    ("🏛️ Building 2", 8),
    ("📚 Library", 7),
    ("🍜 Hostel / Canteen", 5),
    ("🚪 Main Gate", 4),
]

SAFETY_MINS = 2  # buffer on top of walk time, matching the web app

# Plannable stations: home station first, then the transfer stations.
PLAN_STATIONS = [HOME_STATION] + TRANSFER_STATIONS

PLAN_INTRO = "🗺️ *Plan My Trip*\n\nWhere are you right now?"


def _to_mins(hhmm: str) -> int:
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)


def _fmt_mins(n: int) -> str:
    n %= 1440
    return f"{n // 60:02d}:{n % 60:02d}"


def _station_short(station: dict) -> str:
    """'Upper Changi (EW4 · DT32)' → 'Upper Changi' for compact buttons."""
    return station["name"].split(" (")[0]


def plan_location_keyboard() -> InlineKeyboardMarkup:
    rows = []
    locs = list(enumerate(CAMPUS_LOCATIONS))
    for i in range(0, len(locs), 2):
        rows.append(
            [
                InlineKeyboardButton(name, callback_data=f"plan:loc:{idx}")
                for idx, (name, _walk) in locs[i : i + 2]
            ]
        )
    rows.append([InlineKeyboardButton("« Back", callback_data="menu:train")])
    return InlineKeyboardMarkup(rows)


def plan_station_keyboard(loc_idx: int) -> InlineKeyboardMarkup:
    rows = []
    for i in range(0, len(PLAN_STATIONS), 2):
        row = []
        for sidx in range(i, min(i + 2, len(PLAN_STATIONS))):
            tag = "🏠" if sidx == 0 else "🔁"
            row.append(
                InlineKeyboardButton(
                    f"{tag} {_station_short(PLAN_STATIONS[sidx])}",
                    callback_data=f"plan:res:{loc_idx}:{sidx}",
                )
            )
        rows.append(row)
    rows.append([InlineKeyboardButton("« Change location", callback_data="train:plan")])
    return InlineKeyboardMarkup(rows)


def plan_result_keyboard(loc_idx: int, station_idx: int, leave_set: bool = False) -> InlineKeyboardMarkup:
    # When a leave time is in play, offer to change it or snap back to "now";
    # otherwise just offer to set one.
    if leave_set:
        time_row = [
            InlineKeyboardButton("🕐 Change time", callback_data=f"plan:time:{loc_idx}:{station_idx}"),
            InlineKeyboardButton("🔄 Use now", callback_data=f"plan:res:{loc_idx}:{station_idx}"),
        ]
    else:
        time_row = [InlineKeyboardButton("🕐 Set leave time", callback_data=f"plan:time:{loc_idx}:{station_idx}")]
    return InlineKeyboardMarkup(
        [
            time_row,
            [InlineKeyboardButton("🚉 Change station", callback_data=f"plan:loc:{loc_idx}")],
            [InlineKeyboardButton("📍 Change location", callback_data="train:plan")],
            [InlineKeyboardButton("« Back", callback_data="menu:train")],
        ]
    )


def plan_time_prompt(loc_idx: int, station_idx: int) -> str:
    name, _walk = CAMPUS_LOCATIONS[loc_idx]
    station = PLAN_STATIONS[station_idx]
    now = datetime.datetime.now(SGT)
    return (
        "🗺️ *Plan My Trip*\n\n"
        f"📍 From *{name}*   🚉 To *{_station_short(station)}*\n\n"
        "🕐 *What time will you leave?*\n"
        "Type a time like `23:10`, `11pm`, or `2305` — I'll tell you which "
        "trains you can still catch.\n\n"
        f"_Current time: {now.strftime('%H:%M')} (SGT)._"
    )


def plan_time_keyboard(loc_idx: int, station_idx: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("🔄 Use now instead", callback_data=f"plan:res:{loc_idx}:{station_idx}")],
            [InlineKeyboardButton("« Back", callback_data="menu:train")],
        ]
    )


def parse_leave_time(text: str) -> int | None:
    """Parse a typed departure time into minutes-since-midnight, or None.

    Accepts ``now``, 24h (``23:10``, ``23.10``, ``2310``, ``23``) and 12h
    (``11pm``, ``11:10 pm``, ``1110pm``) forms — the shapes students actually
    type. Returns None on anything unrecognisable so the caller can re-prompt.
    """
    s = text.strip().lower()
    if s in ("now", "right now", "leaving now"):
        now = datetime.datetime.now(SGT)
        return now.hour * 60 + now.minute

    ampm = None
    if s.endswith("am"):
        ampm, s = "am", s[:-2]
    elif s.endswith("pm"):
        ampm, s = "pm", s[:-2]
    s = s.strip().replace(".", ":").replace(" ", "")

    if ":" in s:
        parts = s.split(":")
        if len(parts) != 2:
            return None
        hh, mm = parts
    elif s.isdigit() and len(s) in (3, 4):  # 2310 / 905
        hh, mm = s[:-2], s[-2:]
    elif s.isdigit():  # bare hour, e.g. "23" or "11pm" → "11"
        hh, mm = s, "00"
    else:
        return None

    if not (hh.isdigit() and mm.isdigit()):
        return None
    h, m = int(hh), int(mm)
    if ampm == "pm" and h < 12:
        h += 12
    elif ampm == "am" and h == 12:
        h = 0
    if not (0 <= h <= 23 and 0 <= m <= 59):
        return None
    return h * 60 + m


def plan_result_text(loc_idx: int, station_idx: int, leave_mins: int | None = None) -> str:
    name, walk = CAMPUS_LOCATIONS[loc_idx]
    station = PLAN_STATIONS[station_idx]
    now = datetime.datetime.now(SGT)

    # Anchor the verdict to the planned departure if given, else to now.
    if leave_mins is None:
        ref_mins = now.hour * 60 + now.minute
        when_label = f"🕐 Leaving now ({now.strftime('%H:%M')})"
    else:
        ref_mins = leave_mins
        when_label = f"🕐 Leaving {_fmt_mins(leave_mins)}"

    lines = [
        "🗺️ *Plan My Trip*",
        f"📍 From *{name}* (~{walk} min walk)",
        f"🚉 To *{station['name']}*",
        f"{when_label} · +{SAFETY_MINS} min safety\n",
    ]
    for label, trains in station["groups"]:
        lines.append(f"_{label}_")
        for direction, last in trains:
            last_m = _to_mins(last)
            # Last trains run past midnight; treat an already-passed time as tomorrow.
            if last_m < ref_mins - 90:
                last_m += 1440
            leave_by = last_m - walk - SAFETY_MINS
            if ref_mins <= leave_by:
                buf = leave_by - ref_mins
                buf_str = f"{buf // 60}h {buf % 60}m" if buf >= 60 else f"{buf}m"
                lines.append(
                    f"  ✅ {direction} (last {last})\n"
                    f"      leave by {_fmt_mins(leave_by)} · {buf_str} buffer"
                )
            else:
                lines.append(
                    f"  ❌ {direction} (last {last})\n"
                    f"      too late — needed to leave by {_fmt_mins(leave_by)}"
                )
        lines.append("")
    return "\n".join(lines).rstrip()


def route_plan(data: str):
    """Route a ``plan:*`` callback to its (text, keyboard). Returns (None, None)
    for anything unrecognised so the dispatcher can log it."""
    parts = data.split(":")
    if len(parts) == 3 and parts[1] == "loc":
        loc_idx = int(parts[2])
        name, walk = CAMPUS_LOCATIONS[loc_idx]
        text = (
            f"🗺️ *Plan My Trip*\n\n"
            f"📍 From *{name}* (~{walk} min walk)\n\n"
            "Which station do you need?"
        )
        return text, plan_station_keyboard(loc_idx)
    if len(parts) == 4 and parts[1] == "res":
        loc_idx, station_idx = int(parts[2]), int(parts[3])
        return plan_result_text(loc_idx, station_idx), plan_result_keyboard(loc_idx, station_idx)
    return None, None


# ── /command entry points ─────────────────────────────────────────────
async def cmd_trains(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(trains_text(), parse_mode="Markdown")


async def cmd_buses(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = await update.message.reply_text("🚌 Fetching live data…")
    await msg.edit_text(await buses_text(), parse_mode="Markdown")
