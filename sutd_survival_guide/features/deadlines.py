"""Deadlines feature — reads & writes Dylan's bot_data.json.

The original app (dylan_deadline_notifier/bot.py) builds its own Application at
import time and raises without a token, so we don't import it. Instead we use
small data helpers over the *same* JSON file, keeping data compatible. Read-only
views (list/upcoming/stats/modules) plus the add flows (add_module / add_exam /
add_hw) are wired. Adds work two ways:

  • Slash commands — /add_module, /add_exam, /add_hw (power users).
  • Guided button flow — the submenu buttons start a short conversation, with
    per-chat state kept in ``context.user_data['dl_flow']``.

Exams and homework must reference a module the user has already saved (we don't
auto-create); the button flow enforces this by letting you pick from your
modules, and the slash commands reject an unknown module.
"""

import datetime
import json

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

import keyboards as kb
from features import ai
from settings import DEADLINE_DATA_FILE

MAX_MODULE_LEN = 100
MAX_TITLE_LEN = 200
DT_FORMAT = "%Y-%m-%d %H:%M"


def _load() -> dict:
    if DEADLINE_DATA_FILE.exists():
        try:
            return json.loads(DEADLINE_DATA_FILE.read_text())
        except Exception:
            pass
    return {"users": {}, "reminders_sent": {}}


def _save(data: dict) -> None:
    DEADLINE_DATA_FILE.write_text(json.dumps(data, indent=2, default=str))


def _user(data: dict, chat_id) -> dict:
    """Read-only view of a user record (never mutates the store)."""
    return data.get("users", {}).get(str(chat_id), {"modules": [], "items": []})


def _get_user(data: dict, chat_id) -> dict:
    """Get or create the user's record inside ``data`` (caller saves)."""
    users = data.setdefault("users", {})
    key = str(chat_id)
    if key not in users:
        users[key] = {
            "modules": [],
            "items": [],
            "created_at": datetime.datetime.now().isoformat(),
        }
    return users[key]


def _next_id(items: list) -> int:
    return max((int(i.get("id", 0)) for i in items), default=0) + 1


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


# ── Data mutations (shared by slash commands and the button flow) ──────
def user_modules(chat_id) -> list[str]:
    return list(_user(_load(), chat_id).get("modules", []))


def find_module(chat_id, name: str) -> str | None:
    """Return the canonically-saved module matching ``name`` (case-insensitive)."""
    target = " ".join(name.split()).lower()
    for m in user_modules(chat_id):
        if m.lower() == target:
            return m
    return None


def parse_deadline(text: str) -> datetime.datetime | None:
    """Strict ``YYYY-MM-DD HH:MM`` parse (fast, offline)."""
    try:
        return datetime.datetime.strptime(text.strip(), DT_FORMAT)
    except ValueError:
        return None


async def parse_when(text: str) -> datetime.datetime | None:
    """Resolve a due date from free text.

    Tries the strict format first (no network), then falls back to Agnes AI for
    anything natural like "tomorrow 6pm". Returns ``None`` if neither works.
    """
    dt = parse_deadline(text)
    if dt is not None:
        return dt
    return await ai.parse_datetime(text, datetime.datetime.now())


def add_module(chat_id, name: str) -> str:
    """Add a module. Returns a plain-text result message (no Markdown)."""
    name = " ".join(name.split()).strip()
    if not name:
        return "❌ Module name can't be empty."
    if len(name) > MAX_MODULE_LEN:
        return f"⚠️ Module name too long (max {MAX_MODULE_LEN} chars)."
    data = _load()
    user = _get_user(data, chat_id)
    if name.lower() in [m.lower() for m in user["modules"]]:
        return f"⚠️ '{name}' is already in your modules."
    user["modules"].append(name)
    _save(data)
    return f"✅ Added module: {name}"


def add_item(chat_id, kind: str, module: str, title: str, dt: datetime.datetime) -> str:
    """Append an exam/homework item. Returns a plain-text confirmation."""
    data = _load()
    user = _get_user(data, chat_id)
    item = {
        "id": _next_id(user["items"]),
        "type": kind,
        "module": module,
        "title": title,
        "deadline": dt.isoformat(),
        "status": "pending",
        "added_at": datetime.datetime.now().isoformat(),
    }
    user["items"].append(item)
    _save(data)
    reminder = dt - datetime.timedelta(hours=12)
    label = "Exam" if kind == "exam" else "Homework"
    icon = "📝" if kind == "exam" else "📚"
    return (
        f"✅ {label} added:\n\n"
        f"{icon} {title}\n"
        f"📘 {module}\n"
        f"📅 {dt.strftime(DT_FORMAT)}\n"
        f"⏰ Reminder ~12h before: {reminder.strftime(DT_FORMAT)}\n"
        f"🆔 ID: {item['id']}"
    )


def _no_modules_msg() -> str:
    return (
        "📭 You have no modules yet.\n"
        "Add one first with ➕ *Add module* (or `/add_module <name>`), "
        "then add exams and homework under it."
    )


# ── Slash commands ─────────────────────────────────────────────────────
USAGE = {
    "exam": (
        "❌ Usage: /add_exam <module> <title> <YYYY-MM-DD HH:MM>\n\n"
        "Example:\n/add_exam Mathematics Final Paper 2026-08-15 09:00\n\n"
        "The module must already exist — see /add_module."
    ),
    "homework": (
        "❌ Usage: /add_hw <module> <title> <YYYY-MM-DD HH:MM>\n\n"
        "Example:\n/add_hw Mathematics Worksheet 3 2026-07-10 23:59\n\n"
        "The module must already exist — see /add_module."
    ),
}


async def cmd_add_module(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text(
            "❌ Usage: /add_module <module name>\n\n"
            "Example: /add_module Modelling Uncertainty"
        )
        return
    msg = add_module(update.effective_chat.id, " ".join(context.args))
    await update.message.reply_text(msg)


async def cmd_add_exam(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await _cmd_add_item(update, context, "exam")


async def cmd_add_hw(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await _cmd_add_item(update, context, "homework")


def _match_module(chat_id, tokens: list[str]):
    """Split ``tokens`` (module + title words) into (module, title).

    The module name may be several words and isn't quoted, so we match the
    longest saved module that the tokens start with. Returns ``None`` if no
    saved module matches (we never auto-create).
    """
    joined = " ".join(tokens).strip()
    low = joined.lower()
    best = None  # (module, title)
    for m in user_modules(chat_id):
        ml = m.lower()
        if low == ml:
            cand = (m, "")
        elif low.startswith(ml + " "):
            cand = (m, joined[len(m):].strip())
        else:
            continue
        if best is None or len(cand[0]) > len(best[0]):
            best = cand
    return best


async def _cmd_add_item(update: Update, context: ContextTypes.DEFAULT_TYPE, kind: str):
    args = context.args
    # Need at least: module, title, date, time → 4 tokens.
    if len(args) < 4:
        await update.message.reply_text(USAGE[kind])
        return

    dt = parse_deadline(f"{args[-2]} {args[-1]}")
    if dt is None:
        await update.message.reply_text(
            "❌ Invalid date/time. Use: YYYY-MM-DD HH:MM (e.g. 2026-07-20 14:30)"
        )
        return
    if dt < datetime.datetime.now():
        await update.message.reply_text("⚠️ Deadline cannot be in the past.")
        return

    chat_id = update.effective_chat.id
    match = _match_module(chat_id, args[:-2])
    if match is None:
        mods = user_modules(chat_id)
        listing = "\n".join(f"• {m}" for m in mods) if mods else "(none yet)"
        await update.message.reply_text(
            "❌ That module isn't in your saved modules.\n"
            "Add it first with /add_module.\n\n"
            f"Your modules:\n{listing}"
        )
        return

    module, title = match
    if not title:
        await update.message.reply_text(
            "❌ Add a title between the module and the date.\n\n" + USAGE[kind]
        )
        return
    if len(title) > MAX_TITLE_LEN:
        await update.message.reply_text(f"⚠️ Title too long (max {MAX_TITLE_LEN} chars).")
        return

    await update.message.reply_text(add_item(chat_id, kind, module, title, dt))


# ── Guided button flow ─────────────────────────────────────────────────
# State lives in context.user_data['dl_flow']:
#   {"kind": "module"}                                  → waiting for a name
#   {"kind": "exam"|"homework", "step": "title", ...}   → waiting for a title
#   {"kind": ...,             "step": "datetime", ...}   → waiting for a deadline
PROMPT_MODULE = (
    "➕ *Add a module*\n\nSend me the module name.\n\n_Or tap Cancel._"
)


def _when_prompt() -> str:
    """Date/time prompt — invites natural language only when AI can handle it."""
    if ai.is_configured():
        return (
            "📅 When is it due?\n"
            "Type it however you like — e.g. “tomorrow 6pm”, “next Fri 2:30pm”, "
            "“20 Jul 23:59”, or 2026-07-20 14:30."
        )
    return (
        "📅 When is it due?\n"
        "Send the date & time as: YYYY-MM-DD HH:MM\n"
        "Example: 2026-07-20 14:30"
    )


def _when_error() -> str:
    if ai.is_configured():
        return (
            "❓ I couldn't read that as a date. Try again — "
            "e.g. “next Monday 9am” or 2026-07-20 14:30:"
        )
    return "❌ Invalid format. Use YYYY-MM-DD HH:MM (e.g. 2026-07-20 14:30):"


def _cancel_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton("✖️ Cancel", callback_data="dl:cancel")]]
    )


def _module_pick_kb(chat_id, kind: str) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(m[:48], callback_data=f"dl:pick:{kind}:{i}")]
        for i, m in enumerate(user_modules(chat_id))
    ]
    rows.append([InlineKeyboardButton("✖️ Cancel", callback_data="dl:cancel")])
    return InlineKeyboardMarkup(rows)


def start_add_module(context: ContextTypes.DEFAULT_TYPE):
    """Begin the add-module conversation. Returns (text, keyboard)."""
    context.user_data["dl_flow"] = {"kind": "module"}
    return PROMPT_MODULE, _cancel_kb()


def start_add_item(chat_id, kind: str, context: ContextTypes.DEFAULT_TYPE):
    """Begin add-exam / add-hw by offering the user's modules to pick from."""
    if not user_modules(chat_id):
        context.user_data.pop("dl_flow", None)
        return _no_modules_msg(), kb.deadlines_menu()
    noun = "exam" if kind == "exam" else "homework"
    text = f"📝 *Add {noun}*\n\nWhich module is this for?"
    return text, _module_pick_kb(chat_id, kind)


def pick_module(chat_id, data: str, context: ContextTypes.DEFAULT_TYPE):
    """Handle a ``dl:pick:<kind>:<idx>`` tap → ask for the title."""
    _, _, kind, idx = data.split(":")
    mods = user_modules(chat_id)
    try:
        module = mods[int(idx)]
    except (ValueError, IndexError):
        context.user_data.pop("dl_flow", None)
        return "⚠️ That module is no longer available.", kb.deadlines_menu()
    context.user_data["dl_flow"] = {"kind": kind, "module": module, "step": "title"}
    noun = "exam" if kind == "exam" else "homework"
    return (
        f"📝 *Add {noun}* — module *{module}*\n\nSend me the title.",
        _cancel_kb(),
    )


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Free-text step of the guided add flow.

    No-ops unless this chat has an add flow in progress, so it never hijacks
    unrelated messages.
    """
    flow = context.user_data.get("dl_flow")
    if not flow:
        return

    chat_id = update.effective_chat.id
    text = (update.message.text or "").strip()

    if flow["kind"] == "module":
        context.user_data.pop("dl_flow", None)
        await update.message.reply_text(
            add_module(chat_id, text), reply_markup=kb.deadlines_menu()
        )
        return

    step = flow.get("step")
    if step == "title":
        if not text:
            await update.message.reply_text("❌ Title can't be empty. Send a title:")
            return
        if len(text) > MAX_TITLE_LEN:
            await update.message.reply_text(
                f"⚠️ Title too long (max {MAX_TITLE_LEN} chars). Send a shorter one:"
            )
            return
        flow["title"] = text
        flow["step"] = "datetime"
        await update.message.reply_text(_when_prompt(), reply_markup=_cancel_kb())
        return

    if step == "datetime":
        dt = await parse_when(text)
        if dt is None:
            await update.message.reply_text(_when_error())
            return
        if dt < datetime.datetime.now():
            await update.message.reply_text("⚠️ Deadline can't be in the past. Send another:")
            return
        # The module could have been removed mid-flow; re-check before saving.
        module = find_module(chat_id, flow["module"])
        if module is None:
            context.user_data.pop("dl_flow", None)
            await update.message.reply_text(
                f"⚠️ '{flow['module']}' is no longer in your modules.",
                reply_markup=kb.deadlines_menu(),
            )
            return
        msg = add_item(chat_id, flow["kind"], module, flow["title"], dt)
        context.user_data.pop("dl_flow", None)
        await update.message.reply_text(msg, reply_markup=kb.deadlines_menu())
        return
