"""Configuration settings for the Gym Crowd Tracker Telegram Bot."""

import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Telegram Bot Token from BotFather
BOT_TOKEN = os.getenv("BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")

# Maximum gym capacity (adjust based on your gym's actual capacity)
MAX_GYM_CAPACITY = 50

# Occupancy levels and their descriptions
OCCUPANCY_LEVELS = {
    "low": {"min": 0, "max": 30, "color": "🟢", "description": "Low - Plenty of space available"},
    "medium": {"min": 31, "max": 70, "color": "🟡", "description": "Medium - Moderate crowd"},
    "high": {"min": 71, "max": 90, "color": "🟠", "description": "High - Getting crowded"},
    "full": {"min": 91, "max": 100, "color": "🔴", "description": "Full - Near maximum capacity"},
}

# Data file to store gym occupancy (JSON format)
DATA_FILE = "gym_data.json"