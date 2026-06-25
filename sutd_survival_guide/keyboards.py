"""Inline keyboard builders and callback-data scheme for the hub.

Callback data uses a ``namespace:action`` convention so a single dispatcher
can route taps to the right feature:

    menu:main      -> main hub
    menu:gym       -> gym submenu
    menu:deadlines -> deadlines submenu
    menu:train     -> last-train submenu

    gym:status | gym:recent | gym:popular | gym:sim_entry | gym:sim_exit | gym:reset
    dl:list | dl:upcoming | dl:stats | dl:modules | dl:add_module | dl:add_exam | dl:add_hw
    train:trains | train:buses | train:plan

The trip planner is a stateless multi-step flow whose selections live in the
callback data itself (keyboards built in features/last_train.py):

    train:plan                  -> pick campus location
    plan:loc:<loc_idx>          -> pick station
    plan:res:<loc_idx>:<st_idx> -> show "can I catch it?" verdict
"""

from telegram import InlineKeyboardButton, InlineKeyboardMarkup


def _back(target: str = "menu:main", label: str = "« Back to menu") -> list:
    return [InlineKeyboardButton(label, callback_data=target)]


def main_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("🏋️ Gym Crowd", callback_data="menu:gym")],
            [InlineKeyboardButton("📅 Deadlines", callback_data="menu:deadlines")],
            [InlineKeyboardButton("🚆 Last Train Home", callback_data="menu:train")],
        ]
    )


def gym_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("📊 Status", callback_data="gym:status")],
            [
                InlineKeyboardButton("📋 Recent", callback_data="gym:recent"),
                InlineKeyboardButton("⏰ Popular times", callback_data="gym:popular"),
            ],
            [
                InlineKeyboardButton("➡️ Sim entry", callback_data="gym:sim_entry"),
                InlineKeyboardButton("⬅️ Sim exit", callback_data="gym:sim_exit"),
            ],
            [InlineKeyboardButton("🔄 Daily reset", callback_data="gym:reset")],
            _back(),
        ]
    )


def deadlines_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("📋 List", callback_data="dl:list"),
                InlineKeyboardButton("📅 Upcoming", callback_data="dl:upcoming"),
            ],
            [
                InlineKeyboardButton("📘 Modules", callback_data="dl:modules"),
                InlineKeyboardButton("📊 Stats", callback_data="dl:stats"),
            ],
            [InlineKeyboardButton("➕ Add module", callback_data="dl:add_module")],
            [
                InlineKeyboardButton("📝 Add exam", callback_data="dl:add_exam"),
                InlineKeyboardButton("📚 Add homework", callback_data="dl:add_hw"),
            ],
            _back(),
        ]
    )


def train_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("🚆 Last trains", callback_data="train:trains")],
            [InlineKeyboardButton("🚌 Live buses", callback_data="train:buses")],
            [InlineKeyboardButton("🗺️ Plan my trip", callback_data="train:plan")],
            _back(),
        ]
    )
