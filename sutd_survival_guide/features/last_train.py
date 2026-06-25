"""Last Train Home feature — native rebuild of Gabriel's web app.

Three parts mirror the web app's tabs:
  • Trains — static published last-train times (LTA has no live MRT countdown).
  • Buses  — live arrivals via the arrivelah API (server-side fetch here).
  • Plan   — "can I catch the last train?" calculator (guided flow comes next pass).
"""

import httpx
from telegram import Update
from telegram.ext import ContextTypes

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
    import datetime
    try:
        diff = (datetime.datetime.fromisoformat(iso) - datetime.datetime.now(
            datetime.timezone.utc).astimezone()).total_seconds() / 60
    except Exception:
        return "—"
    m = round(diff)
    return "Arr" if m <= 0 else f"{m}m"


# Plan-trip is interactive (location + leave time + station). Stubbed for now.
PLAN_HINT = (
    "🗺️ *Plan My Trip*\n\n"
    "This will calculate whether you can still catch the last train, based on:\n"
    "• where you are on campus (walk time)\n"
    "• when you plan to leave\n"
    "• which station you need\n\n"
    "_Guided flow coming in the next pass._"
)


# ── /command entry points ─────────────────────────────────────────────
async def cmd_trains(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(trains_text(), parse_mode="Markdown")


async def cmd_buses(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = await update.message.reply_text("🚌 Fetching live data…")
    await msg.edit_text(await buses_text(), parse_mode="Markdown")
