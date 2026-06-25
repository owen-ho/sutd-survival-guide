"""Deadlines feature — reads Dylan's bot_data.json.

The original app (dylan_deadline_notifier/bot.py) builds its own Application at
import time and raises without a token, so we don't import it. Instead we use
small data helpers over the *same* JSON file, keeping data compatible. Read-only
views (list/upcoming/stats/modules) are wired; the add/done/remove input flows
are routed to usage hints for this first pass.
"""

import datetime
import json

from telegram import Update
from telegram.ext import ContextTypes

from settings import DEADLINE_DATA_FILE


def _load() -> dict:
    if DEADLINE_DATA_FILE.exists():
        try:
            return json.loads(DEADLINE_DATA_FILE.read_text())
        except Exception:
            pass
    return {"users": {}, "reminders_sent": {}}


def _user(data: dict, chat_id) -> dict:
    return data.get("users", {}).get(str(chat_id), {"modules": [], "items": []})


def list_text(chat_id) -> str:
    user = _user(_load(), chat_id)
    pending = sorted(
        (i for i in user.get("items", []) if i.get("status") == "pending"),
        key=lambda x: x["deadline"],
    )
    if not pending:
        return "🎉 No pending deadlines! All clear."
    lines = [f"📋 *Pending Deadlines ({len(pending)})*\n"]
    for item in pending:
        dt = datetime.datetime.fromisoformat(item["deadline"])
        icon = "📝" if item["type"] == "exam" else "📚"
        lines.append(
            f"{icon} [{item['id']}] {dt.strftime('%b %d, %H:%M')} — "
            f"{item['title']} ({item['module']})"
        )
    lines.append("\n_Use /done <id> or /remove <id> to manage._")
    return "\n".join(lines)


def upcoming_text(chat_id) -> str:
    user = _user(_load(), chat_id)
    now = datetime.datetime.now()
    week = now + datetime.timedelta(days=7)
    pending = sorted(
        (
            i
            for i in user.get("items", [])
            if i.get("status") == "pending"
            and now <= datetime.datetime.fromisoformat(i["deadline"]) <= week
        ),
        key=lambda x: x["deadline"],
    )
    if not pending:
        return "📭 Nothing due in the next 7 days!"
    lines = ["📅 *Upcoming (Next 7 Days)*\n"]
    for item in pending:
        dt = datetime.datetime.fromisoformat(item["deadline"])
        icon = "📝" if item["type"] == "exam" else "📚"
        hrs = (dt - now).total_seconds() / 3600
        urgency = " 🔴 URGENT" if hrs < 24 else (" 🟡 SOON" if hrs < 72 else "")
        lines.append(
            f"{icon} [{item['id']}] {dt.strftime('%a %b %d, %H:%M')} — "
            f"{item['title']} ({item['module']}){urgency}"
        )
    return "\n".join(lines)


def modules_text(chat_id) -> str:
    user = _user(_load(), chat_id)
    mods = user.get("modules", [])
    if not mods:
        return "📭 No modules yet. Add one with `/add_module <name>`."
    lines = [f"{i}. {m}" for i, m in enumerate(mods, 1)]
    return f"📘 *Your Modules ({len(mods)})*\n\n" + "\n".join(lines)


def stats_text(chat_id) -> str:
    user = _user(_load(), chat_id)
    items = user.get("items", [])
    total = len(items)
    completed = len([i for i in items if i.get("status") == "completed"])
    exams = len([i for i in items if i.get("type") == "exam"])
    hw = len([i for i in items if i.get("type") == "homework"])
    rate = round(completed / total * 100) if total else 0
    return (
        "📊 *Statistics*\n\n"
        f"Total items: {total}\n"
        f"Exams: {exams}\n"
        f"Homework/Projects: {hw}\n"
        f"Pending: {total - completed}\n"
        f"Completed: {completed}\n"
        f"Completion rate: {rate}%\n\n"
        f"Modules: {len(user.get('modules', []))}"
    )


# Placeholders for input-driven flows to build next pass.
ADD_MODULE_HINT = (
    "➕ *Add a module*\n\nFor now, type:\n`/add_module Modelling Uncertainty`"
)
ADD_EXAM_HINT = (
    "📝 *Add an exam*\n\nFor now, type:\n"
    "`/add_exam <module> <title> <YYYY-MM-DD HH:MM>`\n\n"
    "Example:\n`/add_exam Mathematics Final 2026-08-15 09:00`"
)
ADD_HW_HINT = (
    "📚 *Add homework*\n\nFor now, type:\n"
    "`/add_hw <module> <title> <YYYY-MM-DD HH:MM>`\n\n"
    "Example:\n`/add_hw \"Data Driven World\" Report 2026-07-12 17:00`"
)
