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

# ── Data files reused from the original apps ──────────────────────────
GYM_DATA_FILE = ROOT / "aloysius_gym_crowd_tracker" / "gym_data.json"
DEADLINE_DATA_FILE = ROOT / "dylan_deadline_notifier" / "bot_data.json"

# Admin chat IDs allowed to run gym staff/admin actions. Empty = allow all
# (handy for a hackathon demo). Put numeric Telegram chat IDs here to lock down.
ADMIN_CHAT_IDS: set[int] = set()
