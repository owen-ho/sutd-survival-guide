"""SUTD Survival Guide — unified Telegram bot.

A single bot/token that routes to three features built by the cohort:
  🏋️  Gym Crowd Tracker   (Aloysius)
  📅  Deadline Notifier    (Dylan)
  🚆  Last Train Home      (Gabriel)

This first pass focuses on the hub + inline-button routing. Read-only views are
fully wired; input-driven flows (gym sim, deadline add, trip planner) are routed
to usage hints to be fleshed out next.
"""

import logging

from telegram import Update
from telegram.constants import ParseMode
from telegram.error import BadRequest
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

import db
import keyboards as kb
from settings import BOT_TOKEN
from features import ai, deadlines, facilities, gym, last_train, metrics

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

WELCOME = (
    "🎓 *SUTD Survival Guide*\n\n"
    "Your one-stop hub for surviving campus life. Pick a tool:\n\n"
    "🏋️ *Gym Crowd* — check how busy the gym is\n"
    "📅 *Deadlines* — track exams & homework\n"
    "🚆 *Last Train Home* — trains, buses & trip planner\n"
    "🏛️ *Facilities* — booking links & live library rooms\n\n"
    "💬 *Just type what you need* — Agnes AI figures out the rest "
    "(e.g. “how busy is the gym?”, “what's due this week?”, "
    "“last train home?”). Or tap a button below / use /menu anytime.\n"
    "_See /agnes for live AI usage._"
)

# Shown when free text can't be routed (or Agnes is off): nudge toward examples.
ROUTE_HELP = (
    "🤖 I didn't quite catch that. Try asking me things like:\n"
    "• “how busy is the gym?”\n"
    "• “what's due this week?”\n"
    "• “when's the last train home?”\n"
    "• “any free library rooms?”\n\n"
    "Or use /menu for buttons."
)


# ── Hub ────────────────────────────────────────────────────────────────
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Deep link: t.me/<bot>?start=join-<code> → join a shared module, then menu.
    if context.args:
        reply = deadlines.handle_start_payload(update.effective_chat.id, context.args[0])
        if reply is not None:
            await update.message.reply_text(
                reply, parse_mode=ParseMode.MARKDOWN, reply_markup=kb.deadlines_menu()
            )
            return
    await update.message.reply_text(
        WELCOME, parse_mode=ParseMode.MARKDOWN, reply_markup=kb.main_menu()
    )


# Maps a submenu callback to (intro text, keyboard).
SUBMENUS = {
    "menu:main": (WELCOME, kb.main_menu),
    "menu:gym": ("🏋️ *Gym Crowd Tracker*\n\nChoose an action:", kb.gym_menu),
    "menu:deadlines": ("📅 *Deadline Notifier*\n\nChoose an action:", kb.deadlines_menu),
    "menu:train": ("🚆 *Last Train Home*\n\nChoose an action:", kb.train_menu),
    "menu:facilities": ("🏛️ *Facilities & Bookings*\n\nChoose an action:", kb.facilities_menu),
}


async def _safe_edit(query, text, keyboard=None):
    """Edit a message, tolerating Telegram's two benign 400s.

    • 'not modified' — re-tapping a button that already shows this exact
      content/markup. Expected, not a failure → ignore.
    • 'can't parse entities' — dynamic content (a module name with '_', a title
      with '*', etc.) broke legacy Markdown. Rather than crash, resend the same
      text with no parse_mode so the user still sees it (as plain text).
    """
    try:
        await query.edit_message_text(
            text, parse_mode=ParseMode.MARKDOWN, reply_markup=keyboard
        )
    except BadRequest as exc:
        msg = str(exc).lower()
        if "not modified" in msg:
            return
        if "parse" in msg or "entities" in msg:
            logger.warning("Markdown parse failed, resending as plain text: %s", exc)
            await query.edit_message_text(text, reply_markup=keyboard)
            return
        raise


async def on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Single dispatcher for every inline button tap."""
    query = update.callback_query
    await query.answer()
    data = query.data
    chat_id = update.effective_chat.id

    # Navigation between menus cancels any half-finished deadline add flow.
    if data in SUBMENUS:
        context.user_data.pop("dl_flow", None)
        text, keyboard = SUBMENUS[data]
        await _safe_edit(query, text, keyboard())
        return

    # Feature actions: render text, keep the submenu's keyboard for easy back-nav.
    text, keyboard = _route_action(data, chat_id, context)
    if text is None:
        return
    if callable(text):  # async coroutine factory (live bus fetch)
        await _safe_edit(query, "⏳ Loading…")
        text = await text()
    await _safe_edit(query, text, keyboard)


def _route_action(data: str, chat_id, context):
    """Return (text_or_coro, keyboard) for a feature action callback."""
    # ── Gym ──
    if data == "gym:status":
        return gym.status_text(), kb.gym_menu()
    if data == "gym:recent":
        return gym.recent_text(), kb.gym_menu()
    if data == "gym:popular":
        return gym.POPULAR_TEXT, kb.gym_menu()
    if data == "gym:sim_entry":
        return gym.SIM_ENTRY_HINT, kb.gym_menu()
    if data == "gym:sim_exit":
        return gym.SIM_EXIT_HINT, kb.gym_menu()
    if data == "gym:reset":
        return gym.reset_text(), kb.gym_menu()

    # ── Deadlines ──
    if data == "dl:list":
        return deadlines.list_text(chat_id), kb.deadlines_menu()
    if data == "dl:upcoming":
        return deadlines.upcoming_text(chat_id), kb.deadlines_menu()
    if data == "dl:modules":
        return deadlines.modules_text(chat_id), kb.deadlines_menu()
    if data == "dl:stats":
        return deadlines.stats_text(chat_id), kb.deadlines_menu()
    if data == "dl:add_module":
        return deadlines.start_add_module(context)
    if data == "dl:join":
        return deadlines.start_join(context)
    if data == "dl:remind":
        return deadlines.start_reminders(chat_id, context)
    if data == "dl:add_exam":
        return deadlines.start_add_item(chat_id, "exam", context)
    if data == "dl:add_hw":
        return deadlines.start_add_item(chat_id, "homework", context)
    if data.startswith("dl:pick:"):
        return deadlines.pick_module(chat_id, data, context)
    if data == "dl:cancel":
        context.user_data.pop("dl_flow", None)
        return "✖️ Cancelled.", kb.deadlines_menu()

    # ── Last Train ──
    if data == "train:trains":
        return last_train.trains_text(), kb.train_menu()
    if data == "train:buses":
        return last_train.buses_text, kb.train_menu()  # coroutine factory
    if data == "train:plan":
        return last_train.PLAN_INTRO, last_train.plan_location_keyboard()
    if data.startswith("plan:"):  # multi-step trip planner (state in callback data)
        return last_train.route_plan(data)

    # ── Facilities ──
    if data == "fac:links":
        return facilities.links_text(), kb.facilities_menu()
    if data == "fac:library":
        return facilities.library_dr_text, kb.facilities_menu()  # coroutine factory

    logger.warning("Unhandled callback: %s", data)
    return None, None


# ── Natural-language front door (Agnes AI is the core) ─────────────────
async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Every free-text message: continue an active flow, else let Agnes route it.

    The router turns plain English ("how busy is the gym?", "what's due this
    week?") into a feature + intent, then we render the same views the buttons
    do. One Agnes call per message — cheap and fast enough to sit on the hot
    path. With Agnes off we degrade to a hint pointing at the button menu.
    """
    # A half-finished guided flow (add/join/remind) owns the next message.
    if context.user_data.get("dl_flow"):
        await deadlines.handle_text(update, context)
        return

    text = (update.message.text or "").strip()
    if not text:
        return

    if not ai.is_configured():
        await update.message.reply_text(
            "🤖 Natural-language mode needs Agnes AI (set `AGNES_AI_TOKEN`). "
            "Use /menu for buttons in the meantime.",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=kb.main_menu(),
        )
        return

    thinking = await update.message.reply_text("🤖 …")
    decision = await ai.route(text)
    reply_text, keyboard = await _dispatch_route(decision, update)
    try:
        await thinking.edit_text(
            reply_text, parse_mode=ParseMode.MARKDOWN, reply_markup=keyboard
        )
    except BadRequest as exc:
        msg = str(exc).lower()
        if "parse" in msg or "entities" in msg:
            await thinking.edit_text(reply_text, reply_markup=keyboard)
        elif "not modified" not in msg:
            raise


async def _dispatch_route(decision, update: Update):
    """Map a router decision to (text, keyboard), matching the button views."""
    if decision is None:  # Agnes unreachable / unparseable
        return ROUTE_HELP, kb.main_menu()

    chat_id = update.effective_chat.id
    feature, intent, reply = decision["feature"], decision["intent"], decision["reply"]

    if feature == "gym":
        if intent == "recent":
            return gym.recent_text(), kb.gym_menu()
        if intent == "popular":
            return gym.POPULAR_TEXT, kb.gym_menu()
        return gym.status_text(), kb.gym_menu()

    if feature == "deadlines":
        if intent == "upcoming":
            return deadlines.upcoming_text(chat_id), kb.deadlines_menu()
        if intent == "modules":
            return deadlines.modules_text(chat_id), kb.deadlines_menu()
        if intent == "stats":
            return deadlines.stats_text(chat_id), kb.deadlines_menu()
        if intent == "add":
            return (
                "➕ Let's add it. Tap *Add exam* or *Add homework* below — I'll "
                "ask for the module, the title, and when it's due (you can type "
                "the date naturally, e.g. “next Fri 2pm”).",
                kb.deadlines_menu(),
            )
        return deadlines.list_text(chat_id), kb.deadlines_menu()

    if feature == "train":
        if intent == "buses":
            return await last_train.buses_text(), kb.train_menu()
        return last_train.trains_text(), kb.train_menu()

    if feature == "facilities":
        if intent == "library":
            return await facilities.library_dr_text(), kb.facilities_menu()
        return facilities.links_text(), kb.facilities_menu()

    # feature == "none": use Agnes's own one-liner, falling back to the hint.
    return (reply or ROUTE_HELP), kb.main_menu()


async def cmd_agnes(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show the live Agnes AI usage panel (calls / latency / cost)."""
    await update.message.reply_text(metrics.summary_text(), parse_mode=ParseMode.MARKDOWN)


async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE):
    """Async error handler (PTB awaits this — a sync lambda would crash).

    Logs ``repr(error)`` so Telegram's ``description`` (the part that actually
    says *why* a 400 happened) shows up in the logs, not just the type.
    """
    logger.error("Error while handling update: %r", context.error)


async def _post_init(app: Application):
    """Cache the bot username so deadline sharing can build t.me deep links."""
    deadlines.BOT_USERNAME = app.bot.username
    logger.info("Bot @%s ready", app.bot.username)


def main():
    if BOT_TOKEN == "YOUR_BOT_TOKEN_HERE":
        raise SystemExit("Set BOT_TOKEN in sutd_survival_guide/.env (see .env.example)")

    db.init()  # create the SQLite schema + one-time JSON migration

    # Generous network timeouts: the default 5s connect can flake on slow links.
    app = (
        Application.builder()
        .token(BOT_TOKEN)
        .post_init(_post_init)
        .connect_timeout(20)
        .read_timeout(20)
        .write_timeout(20)
        .pool_timeout(20)
        .build()
    )

    # Hub
    app.add_handler(CommandHandler(["start", "menu"], start))
    app.add_handler(CommandHandler("agnes", cmd_agnes))  # live AI usage panel

    # Keep the original commands working alongside the buttons.
    app.add_handler(CommandHandler("status", gym.cmd_status))
    app.add_handler(CommandHandler("simulate_entry", gym.cmd_simulate_entry))
    app.add_handler(CommandHandler("simulate_exit", gym.cmd_simulate_exit))
    app.add_handler(CommandHandler("trains", last_train.cmd_trains))
    app.add_handler(CommandHandler("buses", last_train.cmd_buses))

    # Deadline add/join commands (also reachable via the guided button flow).
    app.add_handler(CommandHandler("add_module", deadlines.cmd_add_module))
    app.add_handler(CommandHandler("join", deadlines.cmd_join))
    app.add_handler(CommandHandler("add_exam", deadlines.cmd_add_exam))
    app.add_handler(CommandHandler("add_hw", deadlines.cmd_add_hw))
    app.add_handler(CommandHandler("remind", deadlines.cmd_remind))

    # Free text: continues an active add/join/remind flow, otherwise Agnes AI
    # routes the message to the right feature (the natural-language front door).
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))

    # One dispatcher for every inline button.
    app.add_handler(CallbackQueryHandler(on_callback))

    app.add_error_handler(on_error)

    # Reminder delivery: check every 5 minutes (per-user lead times in db).
    if app.job_queue is not None:
        app.job_queue.run_repeating(
            deadlines.check_reminders, interval=300, first=15
        )
    else:
        logger.warning(
            "JobQueue unavailable — reminders won't be sent. "
            "Install the extra: pip install 'python-telegram-bot[job-queue]'"
        )

    logger.info("SUTD Survival Guide bot starting…")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
