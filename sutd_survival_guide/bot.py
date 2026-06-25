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
)

import keyboards as kb
from settings import BOT_TOKEN
from features import deadlines, gym, last_train

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

WELCOME = (
    "🎓 *SUTD Survival Guide*\n\n"
    "Your one-stop hub for surviving campus life. Pick a tool:\n\n"
    "🏋️ *Gym Crowd* — check how busy the gym is\n"
    "📅 *Deadlines* — track exams & homework\n"
    "🚆 *Last Train Home* — trains, buses & trip planner\n\n"
    "Tap a button below, or use /menu anytime."
)


# ── Hub ────────────────────────────────────────────────────────────────
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        WELCOME, parse_mode=ParseMode.MARKDOWN, reply_markup=kb.main_menu()
    )


# Maps a submenu callback to (intro text, keyboard).
SUBMENUS = {
    "menu:main": (WELCOME, kb.main_menu),
    "menu:gym": ("🏋️ *Gym Crowd Tracker*\n\nChoose an action:", kb.gym_menu),
    "menu:deadlines": ("📅 *Deadline Notifier*\n\nChoose an action:", kb.deadlines_menu),
    "menu:train": ("🚆 *Last Train Home*\n\nChoose an action:", kb.train_menu),
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

    # Navigation between menus.
    if data in SUBMENUS:
        text, keyboard = SUBMENUS[data]
        await _safe_edit(query, text, keyboard())
        return

    # Feature actions: render text, keep the submenu's keyboard for easy back-nav.
    text, keyboard = _route_action(data, chat_id)
    if text is None:
        return
    if callable(text):  # async coroutine factory (live bus fetch)
        await _safe_edit(query, "⏳ Loading…")
        text = await text()
    await _safe_edit(query, text, keyboard)


def _route_action(data: str, chat_id):
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
        return deadlines.ADD_MODULE_HINT, kb.deadlines_menu()
    if data == "dl:add_exam":
        return deadlines.ADD_EXAM_HINT, kb.deadlines_menu()
    if data == "dl:add_hw":
        return deadlines.ADD_HW_HINT, kb.deadlines_menu()

    # ── Last Train ──
    if data == "train:trains":
        return last_train.trains_text(), kb.train_menu()
    if data == "train:buses":
        return last_train.buses_text, kb.train_menu()  # coroutine factory
    if data == "train:plan":
        return last_train.PLAN_HINT, kb.train_menu()

    logger.warning("Unhandled callback: %s", data)
    return None, None


async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE):
    """Async error handler (PTB awaits this — a sync lambda would crash).

    Logs ``repr(error)`` so Telegram's ``description`` (the part that actually
    says *why* a 400 happened) shows up in the logs, not just the type.
    """
    logger.error("Error while handling update: %r", context.error)


def main():
    if BOT_TOKEN == "YOUR_BOT_TOKEN_HERE":
        raise SystemExit("Set BOT_TOKEN in sutd_survival_guide/.env (see .env.example)")

    app = Application.builder().token(BOT_TOKEN).build()

    # Hub
    app.add_handler(CommandHandler(["start", "menu"], start))

    # Keep the original commands working alongside the buttons.
    app.add_handler(CommandHandler("status", gym.cmd_status))
    app.add_handler(CommandHandler("simulate_entry", gym.cmd_simulate_entry))
    app.add_handler(CommandHandler("simulate_exit", gym.cmd_simulate_exit))
    app.add_handler(CommandHandler("trains", last_train.cmd_trains))
    app.add_handler(CommandHandler("buses", last_train.cmd_buses))

    # One dispatcher for every inline button.
    app.add_handler(CallbackQueryHandler(on_callback))

    app.add_error_handler(on_error)

    logger.info("SUTD Survival Guide bot starting…")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
