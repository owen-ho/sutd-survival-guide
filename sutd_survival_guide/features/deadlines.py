"""Deadlines feature — shared modules on SQLite (see db.py).

Per-module sharing: you join a module (by name, by share code, or via a deep
link) and instantly see all of its deadlines. Adding an exam/homework drops it
into a module, so every member sees it at once. Each member keeps their own
done/reminder state.

Adds work two ways — slash commands and a guided button flow — and the due-date
step accepts natural language via Agnes AI (see features/ai.py), falling back to
strict YYYY-MM-DD HH:MM.
"""

import datetime

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

import db
import keyboards as kb
from features import ai

MAX_MODULE_LEN = 100
MAX_TITLE_LEN = 200
DT_FORMAT = "%Y-%m-%d %H:%M"

# Set at startup (bot.py post_init) so we can build t.me deep links.
BOT_USERNAME: str | None = None


# ── Sharing helpers ────────────────────────────────────────────────────
def _share_line(code: str) -> str:
    if BOT_USERNAME:
        return f"🔗 Share: https://t.me/{BOT_USERNAME}?start=join-{code}"
    return f"🔗 Share code: `{code}` — others tap 🔗 Join module or use /join {code}"


# ── Read views ─────────────────────────────────────────────────────────
def list_text(chat_id) -> str:
    pending = [i for i in db.user_deadlines(chat_id) if i["state"] == "pending"]
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
    return "\n".join(lines)


def upcoming_text(chat_id) -> str:
    now = datetime.datetime.now()
    week = now + datetime.timedelta(days=7)
    pending = [
        i
        for i in db.user_deadlines(chat_id)
        if i["state"] == "pending"
        and now <= datetime.datetime.fromisoformat(i["deadline"]) <= week
    ]
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
    mods = db.user_modules(chat_id)
    if not mods:
        return (
            "📭 You haven't joined any modules yet.\n\n"
            "Add one with ➕ *Add module* (or `/add_module <name>`), or join a "
            "classmate's with 🔗 *Join module*."
        )
    lines = [f"📘 *Your Modules ({len(mods)})*\n"]
    for m in mods:
        members = m.get("members", 1)
        who = "just you" if members == 1 else f"{members} members"
        lines.append(f"• *{m['name']}* — {who}")
        lines.append(f"  {_share_line(m['share_code'])}")
    return "\n".join(lines)


def stats_text(chat_id) -> str:
    s = db.stats(chat_id)
    rate = round(s["completed"] / s["total"] * 100) if s["total"] else 0
    return (
        "📊 *Statistics*\n\n"
        f"Total items: {s['total']}\n"
        f"Exams: {s['exams']}\n"
        f"Homework/Projects: {s['homework']}\n"
        f"Pending: {s['pending']}\n"
        f"Completed: {s['completed']}\n"
        f"Completion rate: {rate}%\n\n"
        f"Modules joined: {s['modules']}"
    )


# ── Date parsing ───────────────────────────────────────────────────────
def parse_deadline(text: str) -> datetime.datetime | None:
    """Strict ``YYYY-MM-DD HH:MM`` parse (fast, offline)."""
    try:
        return datetime.datetime.strptime(text.strip(), DT_FORMAT)
    except ValueError:
        return None


async def parse_when(text: str) -> datetime.datetime | None:
    """Resolve a due date from free text: strict first, then Agnes AI."""
    dt = parse_deadline(text)
    if dt is not None:
        return dt
    return await ai.parse_datetime(text, datetime.datetime.now())


# ── Core mutations (shared by slash commands and the button flow) ──────
def add_module(chat_id, name: str) -> str:
    """Create a shared module (or join an existing one by name)."""
    name = _clean(name)
    if not name:
        return "❌ Module name can't be empty."
    if len(name) > MAX_MODULE_LEN:
        return f"⚠️ Module name too long (max {MAX_MODULE_LEN} chars)."
    db.ensure_user(chat_id)
    mod, created = db.get_or_create_module(name, chat_id)
    newly = db.subscribe(chat_id, mod["id"])
    if created:
        return (
            f"✅ Created module: {mod['name']}\n"
            "Everyone who joins it shares its deadlines.\n"
            f"{_share_line(mod['share_code'])}"
        )
    if newly:
        return (
            f"✅ Joined existing shared module: {mod['name']}\n"
            "You'll now see its deadlines.\n"
            f"{_share_line(mod['share_code'])}"
        )
    return f"⚠️ You're already in '{mod['name']}'.\n{_share_line(mod['share_code'])}"


def join_by_code(chat_id, code: str) -> str:
    db.ensure_user(chat_id)
    mod = db.get_module_by_code(code)
    if not mod:
        return f"❌ No module found for code '{code.strip().upper()}'."
    newly = db.subscribe(chat_id, mod["id"])
    if newly:
        return f"✅ Joined *{mod['name']}* — you'll now see its shared deadlines."
    return f"⚠️ You're already in *{mod['name']}*."


def add_item(chat_id, kind: str, module: dict, title: str, dt: datetime.datetime) -> str:
    """Add an exam/homework into ``module`` (visible to all its members)."""
    db.add_deadline(module["id"], kind, title, dt.isoformat(), chat_id)
    members = db.user_modules(chat_id)
    count = next((m.get("members", 1) for m in members if m["id"] == module["id"]), 1)
    reminder = dt - datetime.timedelta(hours=12)
    label = "Exam" if kind == "exam" else "Homework"
    icon = "📝" if kind == "exam" else "📚"
    shared = "" if count <= 1 else f"\n👥 Shared with {count - 1} other member(s)"
    return (
        f"✅ {label} added:\n\n"
        f"{icon} {title}\n"
        f"📘 {module['name']}\n"
        f"📅 {dt.strftime(DT_FORMAT)}\n"
        f"⏰ Reminder ~12h before: {reminder.strftime(DT_FORMAT)}"
        f"{shared}"
    )


def _clean(name: str) -> str:
    return " ".join(name.split()).strip()


# ── Slash commands ─────────────────────────────────────────────────────
USAGE = {
    "exam": (
        "❌ Usage: /add_exam <module> <title> <YYYY-MM-DD HH:MM>\n\n"
        "Example:\n/add_exam Mathematics Final Paper 2026-08-15 09:00\n\n"
        "You must have joined the module — see /add_module or /join."
    ),
    "homework": (
        "❌ Usage: /add_hw <module> <title> <YYYY-MM-DD HH:MM>\n\n"
        "Example:\n/add_hw Mathematics Worksheet 3 2026-07-10 23:59\n\n"
        "You must have joined the module — see /add_module or /join."
    ),
}


async def cmd_add_module(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text(
            "❌ Usage: /add_module <module name>\n\n"
            "Example: /add_module Modelling Uncertainty"
        )
        return
    await update.message.reply_text(
        add_module(update.effective_chat.id, " ".join(context.args)),
        parse_mode="Markdown",
    )


async def cmd_join(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("❌ Usage: /join <share code>")
        return
    await update.message.reply_text(
        join_by_code(update.effective_chat.id, context.args[0]),
        parse_mode="Markdown",
    )


async def cmd_add_exam(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await _cmd_add_item(update, context, "exam")


async def cmd_add_hw(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await _cmd_add_item(update, context, "homework")


def _match_module(chat_id, tokens: list[str]):
    """Split ``tokens`` (module + title words) into (module_dict, title).

    Matches the longest *joined* module the tokens start with. Returns ``None``
    if the user isn't in any module the tokens name.
    """
    joined = " ".join(tokens).strip()
    low = joined.casefold()
    best = None  # (module_dict, title)
    for m in db.user_modules(chat_id):
        ml = m["name"].casefold()
        if low == ml:
            cand = (m, "")
        elif low.startswith(ml + " "):
            cand = (m, joined[len(m["name"]):].strip())
        else:
            continue
        if best is None or len(cand[0]["name"]) > len(best[0]["name"]):
            best = cand
    return best


async def _cmd_add_item(update: Update, context: ContextTypes.DEFAULT_TYPE, kind: str):
    args = context.args
    if len(args) < 4:  # module, title, date, time
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
        mods = db.user_modules(chat_id)
        listing = "\n".join(f"• {m['name']}" for m in mods) if mods else "(none yet)"
        await update.message.reply_text(
            "❌ You haven't joined a module by that name.\n"
            "Add or join it first with /add_module or /join.\n\n"
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
# State in context.user_data['dl_flow']:
#   {"kind": "module"}                                  → waiting for a name
#   {"kind": "join"}                                    → waiting for a code
#   {"kind": "exam"|"homework", "step": "title", ...}   → waiting for a title
#   {"kind": ...,             "step": "datetime", ...}   → waiting for a deadline
PROMPT_MODULE = "➕ *Add a module*\n\nSend me the module name.\n\n_Or tap Cancel._"
PROMPT_JOIN = "🔗 *Join a module*\n\nSend me the share code.\n\n_Or tap Cancel._"


def _when_prompt() -> str:
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
        [InlineKeyboardButton(m["name"][:48], callback_data=f"dl:pick:{kind}:{m['id']}")]
        for m in db.user_modules(chat_id)
    ]
    rows.append([InlineKeyboardButton("✖️ Cancel", callback_data="dl:cancel")])
    return InlineKeyboardMarkup(rows)


def start_add_module(context: ContextTypes.DEFAULT_TYPE):
    context.user_data["dl_flow"] = {"kind": "module"}
    return PROMPT_MODULE, _cancel_kb()


def start_join(context: ContextTypes.DEFAULT_TYPE):
    context.user_data["dl_flow"] = {"kind": "join"}
    return PROMPT_JOIN, _cancel_kb()


def start_add_item(chat_id, kind: str, context: ContextTypes.DEFAULT_TYPE):
    if not db.user_modules(chat_id):
        context.user_data.pop("dl_flow", None)
        return (
            "📭 Join a module first (➕ Add module or 🔗 Join module), then add "
            "exams and homework into it.",
            kb.deadlines_menu(),
        )
    noun = "exam" if kind == "exam" else "homework"
    return f"📝 *Add {noun}*\n\nWhich module is this for?", _module_pick_kb(chat_id, kind)


def pick_module(chat_id, data: str, context: ContextTypes.DEFAULT_TYPE):
    """Handle ``dl:pick:<kind>:<module_id>`` → ask for the title."""
    _, _, kind, mid = data.split(":")
    mod = next((m for m in db.user_modules(chat_id) if str(m["id"]) == mid), None)
    if mod is None:
        context.user_data.pop("dl_flow", None)
        return "⚠️ That module is no longer available.", kb.deadlines_menu()
    context.user_data["dl_flow"] = {
        "kind": kind,
        "module_id": mod["id"],
        "module_name": mod["name"],
        "step": "title",
    }
    noun = "exam" if kind == "exam" else "homework"
    return (
        f"📝 *Add {noun}* — module *{mod['name']}*\n\nSend me the title.",
        _cancel_kb(),
    )


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Free-text step of the guided flows. No-op unless a flow is active."""
    flow = context.user_data.get("dl_flow")
    if not flow:
        return

    chat_id = update.effective_chat.id
    text = (update.message.text or "").strip()

    if flow["kind"] == "module":
        context.user_data.pop("dl_flow", None)
        await update.message.reply_text(
            add_module(chat_id, text), parse_mode="Markdown",
            reply_markup=kb.deadlines_menu(),
        )
        return

    if flow["kind"] == "join":
        context.user_data.pop("dl_flow", None)
        await update.message.reply_text(
            join_by_code(chat_id, text), parse_mode="Markdown",
            reply_markup=kb.deadlines_menu(),
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
        # The module membership could have changed mid-flow; re-check.
        mod = db.find_user_module(chat_id, flow["module_name"])
        if mod is None:
            context.user_data.pop("dl_flow", None)
            await update.message.reply_text(
                f"⚠️ You're no longer in '{flow['module_name']}'.",
                reply_markup=kb.deadlines_menu(),
            )
            return
        msg = add_item(chat_id, flow["kind"], mod, flow["title"], dt)
        context.user_data.pop("dl_flow", None)
        await update.message.reply_text(msg, reply_markup=kb.deadlines_menu())
        return


# ── Deep-link entry (/start join-<code>) ───────────────────────────────
def handle_start_payload(chat_id, payload: str) -> str | None:
    """Return a reply for a ``/start`` deep-link payload, or None if unrelated."""
    if payload.startswith("join-"):
        return join_by_code(chat_id, payload[len("join-"):])
    return None
