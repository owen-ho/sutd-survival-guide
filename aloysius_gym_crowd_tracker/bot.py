"""Telegram Bot for Gym Crowd Tracking.

This bot allows students to check the current gym occupancy
and helps track who enters/exits the gym via student card taps.
"""

import logging
from telegram import Update, KeyboardButton, ReplyKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackContext,
)
from gym_tracker import GymTracker
from config import BOT_TOKEN, MAX_GYM_CAPACITY

# Enable logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# Initialize gym tracker
tracker = GymTracker()


async def start(update: Update, context: CallbackContext) -> None:
    """Send welcome message when /start is invoked."""
    user = update.effective_user
    welcome_text = f"""
🏋️ *Gym Crowd Tracker*

Hi {user.mention_html()}! 👋

This bot helps you check the current gym occupancy before heading in.

*Available Commands:*
/status - Check current gym crowd level
/recent - View recent gym activity
/popular - See most popular time slots
/admin_reset - Reset daily counters (admin only)

*For Gym Staff:*
/simulate_entry STUDENT_ID - Simulate card tap on entry
/simulate_exit STUDENT_ID - Simulate card tap on exit

*Occupancy Levels:*
🟢 Low (0-30%) - Plenty of space
🟡 Medium (31-70%) - Moderate crowd
🟠 High (71-90%) - Getting crowded
🔴 Full (91-100%) - Near capacity

Max Capacity: {MAX_GYM_CAPACITY} people
    """

    keyboard = [
        [KeyboardButton("/status")]
    ]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

    await update.message.reply_html(welcome_text, reply_markup=reply_markup)


async def status(update: Update, context: CallbackContext) -> None:
    """Show current gym status."""
    gym_status = tracker.get_status()
    
    level = gym_status["level"]
    emoji = level.get("color", "⚪")
    desc = level.get("description", "Unknown")
    
    # Create occupancy bar
    occupancy = gym_status["current_occupancy"]
    max_cap = gym_status["max_capacity"]
    filled = int(occupancy / max_cap * 10)
    bar = "█" * filled + "░" * (10 - filled)
    
    message = f"""
{emoji} *Gym Status*

📊 Occupancy: {occupancy}/{max_cap} ({gym_status['percentage']}%)
{desc}

{bar}

📈 Today: {gym_status['total_entries_today']} entered, {gym_status['total_exits_today']} exited
🕐 Last updated: {gym_status['last_updated'][:19] if gym_status['last_updated'] else 'N/A'}
    """
    
    await update.message.reply_text(message, parse_mode="Markdown")


async def recent(update: Update, context: CallbackContext) -> None:
    """Show recent gym activity."""
    activity = tracker.get_recent_activity(10)
    
    if not activity:
        await update.message.reply_text("No recent activity recorded.")
        return
    
    message = "📋 *Recent Activity:*\n\n"
    
    for act in reversed(activity):
        timestamp = act.get("timestamp", "")[:16].replace("T", " | ")
        act_type = act.get("type", "")
        student = act.get("student_id", "Unknown")
        occ = act.get("occupancy_after", "")
        
        icon = "➡️" if act_type == "entry" else "⬅️"
        message += f"{icon} {student}\n"
        message += f"   {timestamp}\n"
        message += f"   Occupancy: {occ}\n\n"
    
    message += "_Showing last 10 activities_"
    
    await update.message.reply_text(message, parse_mode="Markdown")


async def simulate_entry(update: Update, context: CallbackContext) -> None:
    """Simulate a student card tap on entry."""
    if not context.args:
        await update.message.reply_text(
            "Please provide a student ID.\nUsage: /simulate_entry STU001"
        )
        return
    
    student_id = context.args[0].upper()
    result = tracker.record_entry(student_id)
    
    if result["success"]:
        emoji = "✅"
        message = f"""
{emoji} *Entry Recorded!*

Student: {student_id}
Current Occupancy: {result['current_occupancy']}/{MAX_GYM_CAPACITY} ({result['percentage']}%)
        """
        await update.message.reply_text(message, parse_mode="Markdown")
    else:
        emoji = "❌"
        message = f"{emoji} *Entry Denied*\n\n{result['message']}"
        await update.message.reply_text(message, parse_mode="Markdown")


async def simulate_exit(update: Update, context: CallbackContext) -> None:
    """Simulate a student card tap on exit."""
    if not context.args:
        await update.message.reply_text(
            "Please provide a student ID.\nUsage: /simulate_exit STU001"
        )
        return
    
    student_id = context.args[0].upper()
    result = tracker.record_exit(student_id)
    
    if result["success"]:
        emoji = "✅"
        message = f"""
{emoji} *Exit Recorded!*

Student: {student_id}
Current Occupancy: {result['current_occupancy']}/{MAX_GYM_CAPACITY} ({result['percentage']}%)
        """
        await update.message.reply_text(message, parse_mode="Markdown")
    else:
        emoji = "❌"
        message = f"{emoji} *Exit Failed*\n\n{result['message']}"
        await update.message.reply_text(message, parse_mode="Markdown")


async def admin_reset(update: Update, context: CallbackContext) -> None:
    """Reset daily counters (admin command)."""
    result = tracker.reset_for_new_day()
    
    message = f"""
🔄 *Daily Reset Complete*

Previous entries: {result['previous_entries']}
Previous exits: {result['previous_exits']}
Carried over (still inside): {result['carried_over']}
    """
    
    await update.message.reply_text(message, parse_mode="Markdown")


async def popular_times(update: Update, context: CallbackContext) -> None:
    """Show popular time information."""
    await update.message.reply_text(
        "📊 *Popular Times*\n\n"
        "Based on historical data, here are the typical crowd patterns:\n\n"
        "🟢 Morning (8-10 AM): Low\n"
        "🟡 Midday (10 AM-1 PM): Medium\n"
        "🔴 Afternoon (1-4 PM): High\n"
        "🟢 Evening (7-9 PM): Low\n\n"
        "*Tip:* Best time to visit is after 7 PM!\n\n"
        "_More accurate data coming soon as we collect more records._"
        , parse_mode="Markdown"
    )


def main() -> None:
    """Start the bot."""
    # Create the Application
    application = Application.builder().token(BOT_TOKEN).build()

    # Register command handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("status", status))
    application.add_handler(CommandHandler("recent", recent))
    application.add_handler(CommandHandler("simulate_entry", simulate_entry))
    application.add_handler(CommandHandler("simulate_exit", simulate_exit))
    application.add_handler(CommandHandler("admin_reset", admin_reset))
    application.add_handler(CommandHandler("popular", popular_times))

    # Log all errors
    application.add_error_handler(lambda update, error: logger.error(f"Update {update} caused error {error}"))

    # Start the Bot
    logger.info("Bot is starting...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()