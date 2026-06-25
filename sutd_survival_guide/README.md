# 🎓 SUTD Survival Guide — Unified Telegram Bot

One bot that routes to three tools built by the cohort, behind a single
inline-button menu:

| Feature | Origin | Status this pass |
|---------|--------|------------------|
| 🏋️ Gym Crowd Tracker | `aloysius_gym_crowd_tracker/` | Status / Recent / Popular wired (reuses `GymTracker`). Sim entry/exit + reset routed (sim via command for now). |
| 📅 Deadline Notifier | `dylan_deadline_notifier/` | List / Upcoming / Modules / Stats + add module/exam/homework — slash commands **and** guided button flow, natural-language due dates via Agnes AI. **Shared modules** on SQLite: join a module to share its deadlines. |
| 🚆 Last Train Home | `gabriel_sutd_last_train_home.html` | Static last-train times + live buses (arrivelah) wired. Trip planner stubbed. |

## How navigation works

`/start` (or `/menu`) shows a main hub. Tapping a feature opens its submenu;
every submenu has a **« Back to menu** button. A single `CallbackQueryHandler`
in `bot.py` dispatches all taps via a `namespace:action` callback scheme
(see `keyboards.py`).

```
bot.py            # entry point: hub, callback dispatcher, command handlers
keyboards.py      # inline keyboards + callback-data scheme
settings.py       # token + data-file/DB paths
db.py             # SQLite data layer for deadlines (shared modules)
features/
  gym.py          # wraps Aloysius' GymTracker
  deadlines.py    # deadlines feature on top of db.py (add/join flows)
  ai.py           # OpenAI-compatible client (Agnes AI) for free-text dates
  last_train.py   # Gabriel's train data + live bus fetch
```

> Note: this package's config is named `settings.py` (not `config.py`) on
> purpose — the gym app has its own top-level `config` module and we must not
> shadow it when reusing `gym_tracker.py`.

## Shared modules (deadlines)

Deadlines live in a normalized SQLite store (`deadlines.db`, created on first
run; the old per-user `bot_data.json` is migrated in once):

- A **module** is a shared entity with a short **share code**. Joining a module
  means you see all of its deadlines, present and future.
- A **deadline** belongs to a module, so every member sees it at once. Each
  member keeps their own done/reminder state (`item_state`), so one person
  marking something done never changes it for anyone else.
- **Three ways to join a module:** add/type its name (`/add_module Maths` — same
  canonical name = same module), tap **🔗 Join module** and paste a code, or
  open a deep link `https://t.me/<bot>?start=join-<code>`.

SQLite (WAL mode) gives this ACID writes and real uniqueness constraints —
unlike the flat JSON, concurrent read-modify-writes can't clobber each other.

## Setup

```bash
cd sutd_survival_guide
python3 -m venv venv && source venv/bin/activate   # (fish: source venv/bin/activate.fish)
pip install -r requirements.txt
cp .env.example .env        # then paste your BotFather token into .env
python bot.py
```

## What's intentionally left for the next pass

- Gym **simulate entry/exit** as an in-chat prompt (currently via `/simulate_entry STU001`).
- Porting Dylan's 12-hour reminder job onto the unified bot's `JobQueue` (adds
  land in the shared `bot_data.json`, so Dylan's standalone scheduler still
  picks them up in the meantime).
