"""
Homework & Exam Reminder Bot for Students
------------------------------------------
Commands:
  /start      - Welcome message with instructions
  /modules    - Add/view/list your modules
  /add_exam   - Add an exam deadline
  /add_hw     - Add a homework/project deadline
  /list       - List all pending exams and homework
  /done <id>  - Mark an item as completed
  /remove <id>- Delete an item
  /upcoming   - Show what's coming up (next 7 days)
  /help       - Show all commands
"""

import os
from pathlib import Path
import datetime
import json 
from dotenv import load_dotenv

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)

from apscheduler.schedulers.background import BackgroundScheduler

load_dotenv()

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

if not BOT_TOKEN or BOT_TOKEN == "your_bot_token_here":
    raise ValueError("ERROR: Set TELEGRAM_BOT_TOKEN in .env file")

DATA_FILE = Path(__file__).parent / "bot_data.json"

application = ApplicationBuilder().token(BOT_TOKEN).build()
# ────────────────────────
# Data helpers
# ────────────────────────

def load_data():
    """Load data from JSON file."""
    if DATA_FILE.exists():
        try:
            return json.loads(DATA_FILE.read_text())
        except (json.JSONDecodeError, Exception):
            pass
    return {
        "users": {},       # chat_id -> { modules: [], items: [...] }
        "reminders_sent": {},  # item_id -> set of reminder times sent
    }


def save_data(data):
    """Save data to JSON file."""
    DATA_FILE.write_text(json.dumps(data, indent=2, default=str))


def get_user(data, chat_id):
    """Get or create user record."""
    if str(chat_id) not in data["users"]:
        data["users"][str(chat_id)] = {
            "modules": [],
            "items": [],
            "created_at": datetime.datetime.now().isoformat(),
        }
    return data["users"][str(chat_id)]


def next_item_id(items):
    """Generate next unique ID."""
    if not items:
        return 1
    return max(int(i.get("id", 0)) for i in items) + 1


# ────────────────────────
# Handlers
# ────────────────────────

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Welcome message."""
    first_name = update.effective_message.from_user.first_name
    text = f"""🎓 Hello, {first_name}!

I'm your Homework & Exam Reminder Bot. I'll help you track deadlines and send reminders 12 hours before each one.

Use these commands:

/add_module <name> — Add a module/subject
/modules — View your modules
/add_exam <module> <title> <date/time> — Add an exam
/add_hw <module> <title> <date/time> — Add homework/project
/list — See all upcoming deadlines
/upcoming — See what's due soon
/done <id> — Mark something as completed
/remove <id> — Delete an item
/help — Show all commands

Example:
/add_module Modelling Uncertainty
/add_exam Modelling Uncertainty Midterm 2026-07-15 14:00
/add_hw Data Driven World Assignment 3 2026-07-10 23:59
"""
    await update.message.reply_text(text)


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show all available commands."""
    text = """📋 Available Commands:

/start — Start the bot
/help — Show this message

MODULES:
/add_module <name> — Add a module
/modules — List all your modules

DEADLINES:
/add_exam <module> <title> <YYYY-MM-DD HH:MM> — Add exam
/add_hw <module> <title> <YYYY-MM-DD HH:MM> — Add homework
/list — List all pending deadlines
/upcoming — Show next 7 days

MANAGEMENT:
/done <id> — Mark as completed
/remove <id> — Delete an item
/stats — View statistics

Tip: Deadlines are sent as reminders 12 hours before.
"""
    await update.message.reply_text(text)


# ────────────────────────
# Module handlers
# ────────────────────────

async def add_module(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Add a module/subject."""
    args = context.args
    if not args:
        await update.message.reply_text(
            "❌ Usage: /add_module <module name>\n\n"
            "Example: /add_module Modelling Uncertainty"
        )
        return

    module_name = " ".join(args).strip()
    if len(module_name) > 100:
        await update.message.reply_text("⚠️ Module name too long (max 100 chars)")
        return

    data = load_data()
    user = get_user(data, update.effective_chat.id)

    if module_name.lower() in [m.lower() for m in user["modules"]]:
        await update.message.reply_text(f"⚠️ '{module_name}' is already in your modules.")
        return

    user["modules"].append(module_name)
    save_data(data)

    await update.message.reply_text(f"✅ Added module: *{module_name}*", parse_mode="Markdown")


async def list_modules(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """List all modules."""
    data = load_data()
    user = get_user(data, update.effective_chat.id)

    if not user["modules"]:
        await update.message.reply_text(
            "📭 No modules yet. Add some with:\n\n"
            "/add_module Modelling Uncertainty\n"
            "/add_module Designing Energy Systems"
        )
        return

    lines = [f"{i+1}. {m}" for i, m in enumerate(user["modules"], 1)]
    text = f"📘 Your Modules ({len(lines)}):\n\n" + "\n".join(lines)
    await update.message.reply_text(text)


# ────────────────────────
# Deadline handlers
# ────────────────────────

async def add_exam(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Add an exam deadline."""
    args = context.args
    if len(args) < 3:
        await update.message.reply_text(
            "❌ Usage: /add_exam <module> <title> <YYYY-MM-DD HH:MM>\n\n"
            "Examples:\n"
            "/add_exam Mathematics Final Exam 2026-08-15 09:00\n"
            '/add_exam "Modelling Uncertainty" Midterm 2026-07-20 14:30'
        )
        return

    # Parse: everything except last 2 tokens is title, last token is date+time
    # Format: /add_exam <module> <title...> <YYYY-MM-DD HH:MM>
    # We need at least: module, title-part, date, time
    try:
        date_str = args[-2]  # YYYY-MM-DD
        time_str = args[-1]  # HH:MM
        title_parts = args[1:-2]  # middle parts = title
    except IndexError:
        await update.message.reply_text("❌ Invalid format. Need: module title_date_time")
        return

    # Validate date/time
    try:
        deadline_dt = datetime.datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M")
    except ValueError:
        await update.message.reply_text("❌ Invalid date/time format. Use YYYY-MM-DD HH:MM")
        return

    if deadline_dt < datetime.datetime.now():
        await update.message.reply_text("⚠️ Deadline cannot be in the past.")
        return

    module = args[0]
    title = " ".join(title_parts) if title_parts else "Untitled"

    data = load_data()
    user = get_user(data, update.effective_chat.id)

    # Check module exists (warn but allow anyway)
    if module not in user["modules"]:
        reply = f"ℹ️ '{module}' is not in your saved modules.\n"
        reply += "You can add it with /add_module later.\n\n"
    else:
        reply = ""

    item = {
        "id": next_item_id(user["items"]),
        "type": "exam",
        "module": module,
        "title": title,
        "deadline": deadline_dt.isoformat(),
        "status": "pending",
        "added_at": datetime.datetime.now().isoformat(),
    }
    user["items"].append(item)
    save_data(data)

    reminder_time = deadline_dt - datetime.timedelta(hours=12)
    reply += f"""✅ Exam added:

📝 Title: {title}
📘 Module: {module}
📅 Deadline: {deadline_dt.strftime('%Y-%m-%d %H:%M')}
⏰ Reminder will be sent: {reminder_time.strftime('%Y-%m-%d %H:%M')}
🆔 ID: {item['id']}
"""
    await update.message.reply_text(reply.strip())


async def add_hw(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Add a homework/project deadline."""
    args = context.args
    if len(args) < 3:
        await update.message.reply_text(
            "❌ Usage: /add_hw <module> <title> <YYYY-MM-DD HH:MM>\n\n"
            "Examples:\n"
            "/add_hw Mathematics Worksheet 2026-07-10 23:59\n"
            '/add_hw "Data Driven World" Report 2026-07-12 17:00'
        )
        return

    try:
        date_str = args[-2]
        time_str = args[-1]
        title_parts = args[1:-2]
    except IndexError:
        await update.message.reply_text("❌ Invalid format. Need: module title_date_time")
        return

    try:
        deadline_dt = datetime.datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M")
    except ValueError:
        await update.message.reply_text("❌ Invalid date/time format. Use YYYY-MM-DD HH:MM")
        return

    if deadline_dt < datetime.datetime.now():
        await update.message.reply_text("⚠️ Deadline cannot be in the past.")
        return

    module = args[0]
    title = " ".join(title_parts) if title_parts else "Untitled"

    data = load_data()
    user = get_user(data, update.effective_chat.id)

    if module not in user["modules"]:
        reply = f"ℹ️ '{module}' is not in your saved modules.\n"
        reply += "Add it with /add_module later.\n\n"
    else:
        reply = ""

    item = {
        "id": next_item_id(user["items"]),
        "type": "homework",
        "module": module,
        "title": title,
        "deadline": deadline_dt.isoformat(),
        "status": "pending",
        "added_at": datetime.datetime.now().isoformat(),
    }
    user["items"].append(item)
    save_data(data)

    reminder_time = deadline_dt - datetime.timedelta(hours=12)
    reply += f"""✅ Homework added:

📝 Title: {title}
📘 Module: {module}
📅 Deadline: {deadline_dt.strftime('%Y-%m-%d %H:%M')}
⏰ Reminder will be sent: {reminder_time.strftime('%Y-%m-%d %H:%M')}
🆔 ID: {item['id']}
"""
    await update.message.reply_text(reply.strip())


# ────────────────────────
# Listing handlers
# ────────────────────────

async def list_deadlines(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """List all pending deadlines."""
    data = load_data()
    user = get_user(data, update.effective_chat.id)
    pending = [i for i in user["items"] if i["status"] == "pending"]

    if not pending:
        await update.message.reply_text("🎉 No pending deadlines! All clear.")
        return

    pending.sort(key=lambda x: x["deadline"])

    # Group by type
    exams = [i for i in pending if i["type"] == "exam"]
    homeworks = [i for i in pending if i["type"] == "homework"]

    keyboard = []
    lines = []

    if exams:
        lines.append("📝 EXAMS:")
        for item in exams:
            dt = datetime.datetime.fromisoformat(item["deadline"])
            lines.append(f"  [{item['id']}] {dt.strftime('%b %d, %H:%M')} — {item['title']} ({item['module']})")
        lines.append("")

    if homeworks:
        lines.append("📚 HOMEWORK/PROJECTS:")
        for item in homeworks:
            dt = datetime.datetime.fromisoformat(item["deadline"])
            lines.append(f"  [{item['id']}] {dt.strftime('%b %d, %H:%M')} — {item['title']} ({item['module']})")
        lines.append("")

    # Build inline keyboard for quick actions
    for item in pending[:10]:  # Limit to 10 for UI reasons
        keyboard.append([
            InlineKeyboardButton(
                f"✔ Done #{item['id']}",
                callback_data=f"done_{item['id']}"
            ),
            InlineKeyboardButton(
                f"🗑 Remove #{item['id']}",
                callback_data=f"remove_{item['id']}"
            ),
        ])

    text = "📋 Pending Deadlines (" + str(len(pending)) + "):\n\n" + "\n".join(lines)
    if keyboard:
        await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
    else:
        await update.message.reply_text(text)


async def upcoming(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show what's due in the next 7 days."""
    data = load_data()
    user = get_user(data, update.effective_chat.id)
    now = datetime.datetime.now()
    week_later = now + datetime.timedelta(days=7)

    pending = [
        i for i in user["items"]
        if i["status"] == "pending"
        and now <= datetime.datetime.fromisoformat(i["deadline"]) <= week_later
    ]
    pending.sort(key=lambda x: x["deadline"])

    if not pending:
        await update.message.reply_text("📭 Nothing due in the next 7 days!")
        return

    lines = ["📅 Upcoming (Next 7 Days):\n"]
    for item in pending:
        dt = datetime.datetime.fromisoformat(item["deadline"])
        emoji = "📝" if item["type"] == "exam" else "📚"
        days_left = (dt - now).total_seconds() / 3600
        urgency = ""
        if days_left < 24:
            urgency = " 🔴 URGENT"
        elif days_left < 72:
            urgency = " 🟡 SOON"

        lines.append(
            f"  {emoji} [{item['id']}] {dt.strftime('%a %b %d, %H:%M')} — "
            f"{item['title']} ({item['module']}){urgency}"
        )

    await update.message.reply_text("\n".join(lines))


async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show statistics."""
    data = load_data()
    user = get_user(data, update.effective_chat.id)
    total = len(user["items"])
    completed = len([i for i in user["items"] if i["status"] == "completed"])
    pending = total - completed
    exams = len([i for i in user["items"] if i["type"] == "exam"])
    hw = len([i for i in user["items"] if i["type"] == "homework"])

    completion_rate = round(completed / total * 100) if total > 0 else 0

    text = f"""📊 Statistics:

Total Items: {total}
Exams: {exams}
Homework/Projects: {hw}
Pending: {pending}
Completed: {completed}
Completion Rate: {completion_rate}%

Modules: {len(user['modules'])}
"""
    await update.message.reply_text(text)


# ────────────────────────
# Action handlers (inline buttons)
# ────────────────────────

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle inline button callbacks (done/remove)."""
    query = update.callback_query
    await query.answer()

    data = load_data()
    user = get_user(data, update.effective_chat.id)
    action, item_id = query.data.split("_", 1)

    if action == "done":
        for item in user["items"]:
            if str(item["id"]) == item_id:
                item["status"] = "completed"
                item["completed_at"] = datetime.datetime.now().isoformat()
                break
        save_data(data)
        await query.edit_message_text(f"✔️ Item #{item_id} marked as completed! 🎉")

    elif action == "remove":
        original_len = len(user["items"])
        user["items"] = [i for i in user["items"] if str(i["id"]) != item_id]
        if len(user["items"]) < original_len:
            save_data(data)
            await query.edit_message_text(f"🗑️ Item #{item_id} removed.")
        else:
            await query.edit_message_text(f"❌ Item #{item_id} not found.")


# ────────────────────────
# Manual done/remove via command
# ────────────────────────

async def mark_done(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Mark an item as completed via /done <id>."""
    args = context.args
    if not args:
        await update.message.reply_text("Usage: /done <item_id>")
        return

    item_id = args[0]
    data = load_data()
    user = get_user(data, update.effective_chat.id)

    for item in user["items"]:
        if str(item["id"]) == item_id and item["status"] == "pending":
            item["status"] = "completed"
            item["completed_at"] = datetime.datetime.now().isoformat()
            save_data(data)
            await update.message.reply_text(f"✔️ '{item['title']}' marked as completed! 🎉")
            return

    await update.message.reply_text(f"❌ Item #{item_id} not found or already completed.")


async def remove_item(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Remove an item via /remove <id>."""
    args = context.args
    if not args:
        await update.message.reply_text("Usage: /remove <item_id>")
        return

    item_id = args[0]
    data = load_data()
    user = get_user(data, update.effective_chat.id)

    original_len = len(user["items"])
    user["items"] = [i for i in user["items"] if str(i["id"]) != item_id]

    if len(user["items"]) < original_len:
        save_data(data)
        await update.message.reply_text(f"🗑️ Item #{item_id} removed.")
    else:
        await update.message.reply_text(f"❌ Item #{item_id} not found.")


# ────────────────────────
# Reminder checker (runs every 5 minutes)
# ────────────────────────

def check_reminders(app):
    """Check for deadlines that need reminders (12 hours before)."""
    data = load_data()
    now = datetime.datetime.now()
    reminder_window_start = now - datetime.timedelta(minutes=5)
    reminder_window_end = now + datetime.timedelta(minutes=5)

    for chat_id, user in data["users"].items():
        for item in user["items"]:
            if item["status"] != "pending":
                continue

            item_id = str(item["id"])
            key = f"{chat_id}_{item_id}"

            # Skip if reminder already sent
            if key in data.get("reminders_sent", {}):
                continue

            deadline = datetime.datetime.fromisoformat(item["deadline"])
            reminder_time = deadline - datetime.timedelta(hours=12)

            # Check if we're in the reminder window
            if reminder_window_start <= reminder_time <= reminder_window_end:
                try:
                    emoji = "📝" if item["type"] == "exam" else "📚"
                    days_left = (deadline - now).total_seconds() / 3600

                    msg = (
                        f"⏰ REMINDER: {emoji} *{item['title']}*\n"
                        f"Module: {item['module']}\n"
                        f"Deadline: {deadline.strftime('%Y-%m-%d %H:%M')}\n"
                        f"Time remaining: ~{days_left:.0f} hours\n\n"
                        f"This is your 12-hour advance reminder."
                    )

                    app.bot.send_message(
                        chat_id=int(chat_id),
                        text=msg,
                        parse_mode="Markdown",
                    )

                    # Track that we sent this reminder
                    if "reminders_sent" not in data:
                        data["reminders_sent"] = {}
                    data["reminders_sent"][key] = now.isoformat()
                    save_data(data)

                except Exception as e:
                    print(f"Failed to send reminder to {chat_id}: {e}")


# ────────────────────────
# Main
# ────────────────────────

def main():
    """Start the bot."""
    # Load initial data
    load_data()

    # Create application
    app = application.builder().token(BOT_TOKEN).build()

    # Register command handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))

    # Module handlers
    app.add_handler(CommandHandler("add_module", add_module))
    app.add_handler(CommandHandler("modules", list_modules))

    # Deadline handlers
    app.add_handler(CommandHandler("add_exam", add_exam))
    app.add_handler(CommandHandler("add_hw", add_hw))
    app.add_handler(CommandHandler("list", list_deadlines))
    app.add_handler(CommandHandler("upcoming", upcoming))
    app.add_handler(CommandHandler("stats", stats))

    # Management handlers
    app.add_handler(CommandHandler("done", mark_done))
    app.add_handler(CommandHandler("remove", remove_item))

    # Inline button handler
    app.add_handler(CallbackQueryHandler(button_handler))

    # Schedule reminder checks every 5 minutes
    scheduler = BackgroundScheduler()
    scheduler.add_job(check_reminders, "interval", minutes=5, args=[app])
    scheduler.start()

    print("🤖 Homework & Exam Reminder Bot is running...")
    print("Send /start to begin.")
    print("Reminders are checked every 5 minutes.")

    # Run the bot
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()