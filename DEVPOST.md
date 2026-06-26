# SSG — SUTD Survival Guide

## Inspiration

Surviving life at SUTD means juggling a dozen little questions every day: *Is the gym packed right now? What's due this week? Did I miss the last train home? Is there a free discussion room?* The answers were scattered across separate apps, spreadsheets, and group chats — and over our cohort, four different people had each built a tool solving one piece of it. We wanted to stitch those four projects into a single front door, and make it answer in the most natural way possible: plain English.

## What it does

SSG is one Telegram bot that unifies four campus-life tools behind a single menu:

- 🏋️ **Gym Crowd Tracker** — live status, recent trend, and busiest hours.
- 📅 **Deadline Notifier** — shared modules on SQLite, natural-language due dates, and per-user reminders that survive restarts.
- 🚆 **Last Train Home** — static last-train times plus live bus arrivals.
- 🏛️ **Facilities & Bookings** — one-tap booking links, live library discussion-room availability, and a room finder ("Think Tank 6" → `1.408`).

The headline isn't the menu — it's that **every** free-text message goes through one **Agnes AI** call that classifies it into a feature + intent and renders the same view a button would. You just type "how busy is the gym?" or "what's due this week?" and it routes you. Buttons remain as a deterministic fallback, so the bot still works with the AI key unset.

## How we built it

A single Python bot built on `python-telegram-bot`, with one `CallbackQueryHandler` dispatching all taps via a `namespace:action` callback scheme. Each teammate's original app became a feature module (`gym.py`, `deadlines.py`, `last_train.py`, `facilities.py`) wrapped behind a shared interface. Agnes AI is reached through a tiny OpenAI-compatible `httpx` client — no SDK — handling routing, natural-language due dates, and reminder parsing, with every call timed and counted so `/agnes` can show the "cheap + fast" story live (calls, latency, tokens, estimated cost). Deadlines live in a normalized SQLite store (WAL mode) for shared modules with real uniqueness constraints, and the whole thing self-hosts via Docker.

## Challenges we ran into

- **Four codebases, four styles.** Merging independent student projects meant reconciling config, data formats, and naming — e.g. keeping our `settings.py` from shadowing the gym app's own `config` module.
- **An LLM on the hot path of every message.** Putting an AI call in front of *every* free-text message only works if it's fast and cheap; a frontier model would push users back to menus.
- **A flaky endpoint.** The Agnes endpoint timed out intermittently (~1 in 4 on some networks), so we added a single retry on the hot path to turn most transient failures into a slightly slower success instead of a dropped reply.
- **Concurrency.** Flat JSON couldn't handle concurrent read-modify-writes for shared modules without clobbering, which pushed us to SQLite with ACID writes.

## Accomplishments that we're proud of

- A genuinely **conversational front door** — type what you need, no menu-hunting — backed by a deterministic button fallback so it never hard-fails.
- **Shared modules**: join a module by name, share code, or deep link, and everyone sees the same deadlines while keeping their own done/reminder state.
- **Reminders that actually survive restarts**, firing once per (user, deadline, lead-time) and skipping lead times that already elapsed.
- A live `/agnes` panel that turns "cheap + fast AI" from a claim into a measured number.

## What we learned

Cheap, fast inference unlocks a different architecture: it's economical to put an LLM call on *every* message instead of forcing users into rigid menus. We also learned how much graceful degradation matters — designing every AI path to fall back to buttons or strict parsing meant the bot stays useful even when the key is unset or the network fails. And merging four projects taught us that clean module boundaries and a shared data layer matter more than any individual feature.

## What's next for SSG — SUTD Survival Guide

- Finish the **trip planner** and gym **sim entry/exit** flows beyond their current stubs/commands.
- Expand facilities coverage to more bookable spaces and richer availability.
- Smarter Agnes routing with multi-intent and follow-up context ("…and remind me the day before").
- Proactive nudges (gym quiet now, room just freed up) and broader rollout across the cohort.
