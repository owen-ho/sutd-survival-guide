"""Gym crowd feature — thin wrapper over Aloysius' GymTracker.

The original tracking logic lives in ``aloysius_gym_crowd_tracker/gym_tracker.py``.
We reuse it as-is and only build the message strings here. Read-only actions
(status/recent/popular) are fully wired. The input-driven staff actions
(simulate entry/exit) are routed to a usage prompt for this first pass.
"""

import sys

from telegram import Update
from telegram.ext import ContextTypes

from settings import GYM_DATA_FILE, ROOT

# Make the original app importable, then reuse its tracker + capacity.
# NB: the gym app has its own top-level ``config`` module. Our package config
# is named ``settings`` precisely so it doesn't shadow the gym one here.
sys.path.insert(0, str(ROOT / "aloysius_gym_crowd_tracker"))
from gym_tracker import GymTracker  # noqa: E402  (loads gym's config module)
from config import MAX_GYM_CAPACITY  # noqa: E402  (gym app's own config)

tracker = GymTracker(data_file=str(GYM_DATA_FILE))


def status_text() -> str:
    s = tracker.get_status()
    level = s["level"]
    occ, cap = s["current_occupancy"], s["max_capacity"]
    filled = int(occ / cap * 10) if cap else 0
    bar = "█" * filled + "░" * (10 - filled)
    return (
        f"{level.get('color', '⚪')} *Gym Status*\n\n"
        f"📊 Occupancy: {occ}/{cap} ({s['percentage']}%)\n"
        f"{level.get('description', 'Unknown')}\n\n"
        f"{bar}\n\n"
        f"📈 Today: {s['total_entries_today']} entered, {s['total_exits_today']} exited\n"
        f"🕐 Last updated: {s['last_updated'][:19] if s['last_updated'] else 'N/A'}"
    )


def recent_text() -> str:
    activity = tracker.get_recent_activity(10)
    if not activity:
        return "📋 *Recent Activity*\n\nNo recent activity recorded."
    lines = ["📋 *Recent Activity*\n"]
    for act in reversed(activity):
        ts = act.get("timestamp", "")[:16].replace("T", " | ")
        icon = "➡️" if act.get("type") == "entry" else "⬅️"
        lines.append(
            f"{icon} {act.get('student_id', 'Unknown')}\n"
            f"   {ts}  ·  Occupancy: {act.get('occupancy_after', '')}"
        )
    lines.append("\n_Showing last 10 activities_")
    return "\n".join(lines)


POPULAR_TEXT = (
    "⏰ *Popular Times*\n\n"
    "Typical crowd patterns:\n\n"
    "🟢 Morning (8–10 AM): Low\n"
    "🟡 Midday (10 AM–1 PM): Medium\n"
    "🔴 Afternoon (1–4 PM): High\n"
    "🟢 Evening (7–9 PM): Low\n\n"
    "*Tip:* Best time to visit is after 7 PM!"
)

# Placeholder for the input-driven staff flows we'll build next pass.
SIM_ENTRY_HINT = (
    "➡️ *Simulate Entry*\n\n"
    "Records a student card-tap on the way in.\n"
    "For now, type:\n`/simulate_entry STU001`"
)
SIM_EXIT_HINT = (
    "⬅️ *Simulate Exit*\n\n"
    "Records a student card-tap on the way out.\n"
    "For now, type:\n`/simulate_exit STU001`"
)


def reset_text() -> str:
    r = tracker.reset_for_new_day()
    return (
        "🔄 *Daily Reset Complete*\n\n"
        f"Previous entries: {r['previous_entries']}\n"
        f"Previous exits: {r['previous_exits']}\n"
        f"Carried over (still inside): {r['carried_over']}"
    )


# ── /command entry points (kept so typed commands still work) ──────────
async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(status_text(), parse_mode="Markdown")


async def cmd_simulate_entry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /simulate_entry STU001")
        return
    r = tracker.record_entry(context.args[0].upper())
    if r["success"]:
        await update.message.reply_text(
            f"✅ Entry recorded — {context.args[0].upper()} "
            f"({r['current_occupancy']}/{MAX_GYM_CAPACITY}, {r['percentage']}%)"
        )
    else:
        await update.message.reply_text(f"❌ {r['message']}")


async def cmd_simulate_exit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /simulate_exit STU001")
        return
    r = tracker.record_exit(context.args[0].upper())
    if r["success"]:
        await update.message.reply_text(
            f"✅ Exit recorded — {context.args[0].upper()} "
            f"({r['current_occupancy']}/{MAX_GYM_CAPACITY}, {r['percentage']}%)"
        )
    else:
        await update.message.reply_text(f"❌ {r['message']}")
