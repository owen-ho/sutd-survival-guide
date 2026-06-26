# 🎓 SUTD Survival Guide — Unified Telegram Bot

One bot that routes to four tools built by the cohort, behind a single
inline-button menu:

| Feature | Origin | Status this pass |
|---------|--------|------------------|
| 🏋️ Gym Crowd Tracker | `aloysius_gym_crowd_tracker/` | Status / Recent / Popular wired (reuses `GymTracker`). Sim entry/exit + reset routed (sim via command for now). |
| 📅 Deadline Notifier | `dylan_deadline_notifier/` | List / Upcoming / Modules / Stats + add module/exam/homework — slash commands **and** guided button flow, natural-language due dates via Agnes AI. **Shared modules** on SQLite: join a module to share its deadlines. |
| 🚆 Last Train Home | `gabriel_sutd_last_train_home.html` | Static last-train times + live buses (arrivelah) wired. Trip planner stubbed. |
| 🏛️ Facilities & Bookings | `facilities.md` | One-tap booking links (Housing/StarRez, Jam Room, Library, Fab Lab) + **live earliest availability** for the 4 library discussion rooms, scraped from the public availability grid. |

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
  facilities.py   # booking links + live library DR availability scraper
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

## Reminders (per-user)

The bot delivers reminders itself via PTB's `JobQueue` (checked every 5 min).
Each user sets their own lead time(s) — default **12 h before** — and can have
several (e.g. *1 day and 2 hours before*):

- Set them with **⏰ Reminders** in the menu, or `/remind <when>`. The input is
  natural language, parsed by Agnes AI (*"the day before and an hour before"* →
  reminders at 1 day and 1 hour), with an offline `1d, 2h` fallback when AI is off.
- Reminders fire once per `(user, deadline, lead-time)` and survive restarts
  (a lead time that came due during downtime still fires). A lead time that had
  already elapsed when the deadline was *added* is skipped, so a "1 day before"
  reminder never fires on something due in an hour.

> Needs the `job-queue` extra (already in `requirements.txt`). Without it the bot
> still runs, but logs a warning and sends no reminders.

## Setup

```bash
cd sutd_survival_guide
python3 -m venv venv && source venv/bin/activate   # (fish: source venv/bin/activate.fish)
pip install -r requirements.txt
cp .env.example .env        # then paste your BotFather token into .env
python bot.py
```

## Self-host with Docker

Files live at the **repo root** (`Dockerfile`, `docker-compose.yml`, `.env.example`)
because the bot imports the gym tracker from a sibling app, so the build context
is the whole repo.

```bash
cd ..                       # repo root
cp .env.example .env        # paste your BotFather token (+ optional Agnes AI key)
docker compose up -d --build
docker compose logs -f bot  # follow the bot
```

- **`bot`** — long-polling Telegram bot; no inbound ports. Its SQLite DB and gym
  counts persist in the named volume `sutd-data` (mounted at `/data`, wired via
  the `DEADLINE_DB_FILE` / `GYM_DATA_FILE` env overrides in `settings.py`).
- **`pitch`** — serves `pitch.html` at <http://localhost:8080> (the 3-slide deck).

Stop with `docker compose down` (add `-v` to also wipe the data volume).

## What's intentionally left for the next pass

- Gym **simulate entry/exit** as an in-chat prompt (currently via `/simulate_entry STU001`).
- **Done/remove** actions on deadlines in the unified bot (the schema tracks
  per-user `item_state`, but there's no button/command for it yet).
