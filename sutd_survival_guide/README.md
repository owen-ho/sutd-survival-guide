# 🎓 SUTD Survival Guide — Unified Telegram Bot

One bot that routes to three tools built by the cohort, behind a single
inline-button menu:

| Feature | Origin | Status this pass |
|---------|--------|------------------|
| 🏋️ Gym Crowd Tracker | `aloysius_gym_crowd_tracker/` | Status / Recent / Popular wired (reuses `GymTracker`). Sim entry/exit + reset routed (sim via command for now). |
| 📅 Deadline Notifier | `dylan_deadline_notifier/` | List / Upcoming / Modules / Stats wired (reads same `bot_data.json`). Add module/exam/homework wired — slash commands **and** guided button flow, with natural-language due dates via Agnes AI. |
| 🚆 Last Train Home | `gabriel_sutd_last_train_home.html` | Static last-train times + live buses (arrivelah) wired. Trip planner stubbed. |

## How navigation works

`/start` (or `/menu`) shows a main hub. Tapping a feature opens its submenu;
every submenu has a **« Back to menu** button. A single `CallbackQueryHandler`
in `bot.py` dispatches all taps via a `namespace:action` callback scheme
(see `keyboards.py`).

```
bot.py            # entry point: hub, callback dispatcher, command handlers
keyboards.py      # inline keyboards + callback-data scheme
settings.py       # token + paths to the original apps' data files
features/
  gym.py          # wraps Aloysius' GymTracker
  deadlines.py    # reads + writes Dylan's bot_data.json (add flows)
  ai.py           # OpenAI-compatible client (Agnes AI) for free-text dates
  last_train.py   # Gabriel's train data + live bus fetch
```

> Note: this package's config is named `settings.py` (not `config.py`) on
> purpose — the gym app has its own top-level `config` module and we must not
> shadow it when reusing `gym_tracker.py`.

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
