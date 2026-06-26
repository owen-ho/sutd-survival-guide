"""Configuration for the unified SUTD Survival Guide bot.

One bot token drives the whole hub. Each feature reuses the data files
created by the original standalone apps so nothing is duplicated.
"""

import os
from pathlib import Path

from dotenv import load_dotenv

# Project root = the folder that contains the three original apps.
ROOT = Path(__file__).resolve().parent.parent

load_dotenv(Path(__file__).resolve().parent / ".env")

BOT_TOKEN = os.getenv("BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")

# ── Agnes AI (OpenAI-compatible) — natural-language date parsing ───────
# Used to turn free-text due dates ("next Fri 2pm") into a timestamp. If the
# token is unset, the deadline flow falls back to the strict YYYY-MM-DD HH:MM.
AGNES_AI_TOKEN = os.getenv("AGNES_AI_TOKEN", "")
AGNES_AI_BASE_URL = os.getenv("AGNES_AI_BASE_URL", "https://apihub.agnes-ai.com/v1")
AGNES_AI_MODEL = os.getenv("AGNES_AI_MODEL", "agnes-2.0-flash")

# Blended price per 1M tokens, used only to show a running cost estimate in the
# /agnes usage panel (the "cheap" half of the pitch). Override to match the
# model's real rate; the default is deliberately conservative.
AGNES_AI_PRICE_PER_1M = float(os.getenv("AGNES_AI_PRICE_PER_1M", "0.20"))

# ── Data files reused from the original apps ──────────────────────────
# Paths are overridable via env so they can point at a mounted Docker volume
# (e.g. DEADLINE_DB_FILE=/data/deadlines.db) and survive container restarts.
GYM_DATA_FILE = Path(
    os.getenv("GYM_DATA_FILE", ROOT / "aloysius_gym_crowd_tracker" / "gym_data.json")
)

# Deadlines now live in SQLite (shared modules + per-user state). The old
# per-user JSON is the one-time migration source on first run.
DEADLINE_DATA_FILE = ROOT / "dylan_deadline_notifier" / "bot_data.json"
DEADLINE_DB_FILE = Path(
    os.getenv("DEADLINE_DB_FILE", Path(__file__).resolve().parent / "deadlines.db")
)

# Admin chat IDs allowed to run gym staff/admin actions. Empty = allow all
# (handy for a hackathon demo). Put numeric Telegram chat IDs here to lock down.
ADMIN_CHAT_IDS: set[int] = set()
