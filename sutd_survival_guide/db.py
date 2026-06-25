"""SQLite data layer for the deadlines feature (shared modules).

Design — per-module sharing:
  • A *module* is a shared, canonically-named entity with a short share code.
  • Users *join* modules (``module_subscriptions``); joining a module means you
    see all of its deadlines, current and future.
  • A *deadline* belongs to a module, so it's visible to every member at once.
  • Per-user state (done / reminder-sent) lives in ``item_state``, keyed by
    (user, deadline) — so one member marking a deadline done never affects
    another member.

Modules are identified by their canonical name (trimmed, case-folded), so two
classmates typing the same module name land in the same shared module. Share
codes / deep links let people join a module without retyping its exact name.

Storage is a single SQLite file (WAL mode) — ACID and safe under the bot's
concurrent read-modify-writes, unlike the old flat JSON.
"""

import datetime
import json
import secrets
import sqlite3
from contextlib import contextmanager

from settings import DEADLINE_DATA_FILE, DEADLINE_DB_FILE

# Unambiguous alphabet for share codes (no 0/O/1/I).
_CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
_CODE_LEN = 6

_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    chat_id    INTEGER PRIMARY KEY,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS modules (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    name       TEXT NOT NULL,            -- display name (first creator's casing)
    name_key   TEXT NOT NULL UNIQUE,     -- canonical key for matching
    share_code TEXT NOT NULL UNIQUE,
    created_by INTEGER,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS module_subscriptions (
    user_id   INTEGER NOT NULL,
    module_id INTEGER NOT NULL,
    joined_at TEXT NOT NULL,
    PRIMARY KEY (user_id, module_id),
    FOREIGN KEY (module_id) REFERENCES modules(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS deadlines (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    module_id  INTEGER NOT NULL,
    type       TEXT NOT NULL,            -- 'exam' | 'homework'
    title      TEXT NOT NULL,
    deadline   TEXT NOT NULL,            -- ISO 8601 (naive local)
    created_by INTEGER,
    status     TEXT NOT NULL DEFAULT 'active',   -- 'active' | 'cancelled'
    created_at TEXT NOT NULL,
    FOREIGN KEY (module_id) REFERENCES modules(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS item_state (
    user_id          INTEGER NOT NULL,
    deadline_id      INTEGER NOT NULL,
    status           TEXT NOT NULL DEFAULT 'pending',  -- 'pending' | 'completed'
    completed_at     TEXT,
    reminder_sent_at TEXT,
    PRIMARY KEY (user_id, deadline_id),
    FOREIGN KEY (deadline_id) REFERENCES deadlines(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_deadlines_module ON deadlines(module_id);
CREATE INDEX IF NOT EXISTS idx_subs_user ON module_subscriptions(user_id);
"""


# ── Connection ─────────────────────────────────────────────────────────
@contextmanager
def _conn():
    conn = sqlite3.connect(DEADLINE_DB_FILE)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def _now() -> str:
    return datetime.datetime.now().isoformat()


def _canon(name: str) -> str:
    return " ".join(name.split()).casefold()


def _clean(name: str) -> str:
    return " ".join(name.split()).strip()


# ── Init + migration ───────────────────────────────────────────────────
def init() -> None:
    with _conn() as c:
        c.execute("PRAGMA journal_mode = WAL")
        c.executescript(_SCHEMA)
        empty = c.execute("SELECT COUNT(*) FROM modules").fetchone()[0] == 0
    if empty:
        _migrate_from_json()


def _migrate_from_json() -> None:
    """One-time import of Dylan's per-user bot_data.json into the shared model."""
    if not DEADLINE_DATA_FILE.exists():
        return
    try:
        data = json.loads(DEADLINE_DATA_FILE.read_text())
    except Exception:
        return

    for chat_id, user in data.get("users", {}).items():
        try:
            uid = int(chat_id)
        except (TypeError, ValueError):
            continue
        ensure_user(uid)
        # Saved modules → shared modules the user joins.
        for name in user.get("modules", []):
            mod, _ = get_or_create_module(name, uid)
            subscribe(uid, mod["id"])
        # Each per-user item → a deadline in its module (+ the user joins it).
        for item in user.get("items", []):
            name = item.get("module") or "General"
            mod, _ = get_or_create_module(name, uid)
            subscribe(uid, mod["id"])
            did = add_deadline(
                mod["id"],
                item.get("type", "homework"),
                item.get("title", "Untitled"),
                item.get("deadline", _now()),
                uid,
                created_at=item.get("added_at"),
            )
            if item.get("status") == "completed":
                set_status(uid, did, "completed", at=item.get("completed_at"))


# ── Users ──────────────────────────────────────────────────────────────
def ensure_user(chat_id: int) -> None:
    with _conn() as c:
        c.execute(
            "INSERT OR IGNORE INTO users (chat_id, created_at) VALUES (?, ?)",
            (chat_id, _now()),
        )


# ── Modules ────────────────────────────────────────────────────────────
def _gen_code(c) -> str:
    while True:
        code = "".join(secrets.choice(_CODE_ALPHABET) for _ in range(_CODE_LEN))
        if not c.execute(
            "SELECT 1 FROM modules WHERE share_code = ?", (code,)
        ).fetchone():
            return code


def get_or_create_module(name: str, chat_id: int) -> tuple[dict, bool]:
    """Return (module, created). Matches on canonical name across all users."""
    key = _canon(name)
    with _conn() as c:
        row = c.execute("SELECT * FROM modules WHERE name_key = ?", (key,)).fetchone()
        if row:
            return dict(row), False
        code = _gen_code(c)
        cur = c.execute(
            "INSERT INTO modules (name, name_key, share_code, created_by, created_at)"
            " VALUES (?, ?, ?, ?, ?)",
            (_clean(name), key, code, chat_id, _now()),
        )
        row = c.execute(
            "SELECT * FROM modules WHERE id = ?", (cur.lastrowid,)
        ).fetchone()
        return dict(row), True


def get_module_by_code(code: str) -> dict | None:
    with _conn() as c:
        row = c.execute(
            "SELECT * FROM modules WHERE share_code = ?", (code.strip().upper(),)
        ).fetchone()
        return dict(row) if row else None


def find_user_module(user_id: int, name: str) -> dict | None:
    """A module the user has joined whose canonical name matches ``name``."""
    key = _canon(name)
    with _conn() as c:
        row = c.execute(
            "SELECT m.* FROM modules m "
            "JOIN module_subscriptions s ON s.module_id = m.id "
            "WHERE s.user_id = ? AND m.name_key = ?",
            (user_id, key),
        ).fetchone()
        return dict(row) if row else None


def user_modules(user_id: int) -> list[dict]:
    """Modules the user has joined, each with a live member count."""
    with _conn() as c:
        rows = c.execute(
            "SELECT m.*, "
            "(SELECT COUNT(*) FROM module_subscriptions x WHERE x.module_id = m.id)"
            "  AS members "
            "FROM modules m "
            "JOIN module_subscriptions s ON s.module_id = m.id "
            "WHERE s.user_id = ? ORDER BY m.name COLLATE NOCASE",
            (user_id,),
        ).fetchall()
        return [dict(r) for r in rows]


def is_subscribed(user_id: int, module_id: int) -> bool:
    with _conn() as c:
        return c.execute(
            "SELECT 1 FROM module_subscriptions WHERE user_id = ? AND module_id = ?",
            (user_id, module_id),
        ).fetchone() is not None


def subscribe(user_id: int, module_id: int) -> bool:
    """Join a module. Returns True if newly joined, False if already a member."""
    with _conn() as c:
        cur = c.execute(
            "INSERT OR IGNORE INTO module_subscriptions (user_id, module_id, joined_at)"
            " VALUES (?, ?, ?)",
            (user_id, module_id, _now()),
        )
        return cur.rowcount > 0


def unsubscribe(user_id: int, module_id: int) -> None:
    with _conn() as c:
        c.execute(
            "DELETE FROM module_subscriptions WHERE user_id = ? AND module_id = ?",
            (user_id, module_id),
        )


# ── Deadlines ──────────────────────────────────────────────────────────
def add_deadline(
    module_id: int,
    kind: str,
    title: str,
    deadline_iso: str,
    chat_id: int,
    created_at: str | None = None,
) -> int:
    with _conn() as c:
        cur = c.execute(
            "INSERT INTO deadlines (module_id, type, title, deadline, created_by, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (module_id, kind, title, deadline_iso, chat_id, created_at or _now()),
        )
        return cur.lastrowid


def user_deadlines(user_id: int) -> list[dict]:
    """Active deadlines across the user's joined modules, with their own state.

    Each dict: id, type, title, deadline, module, state ('pending'|'completed').
    Sorted by deadline ascending.
    """
    with _conn() as c:
        rows = c.execute(
            "SELECT d.id, d.type, d.title, d.deadline, m.name AS module, "
            "       COALESCE(st.status, 'pending') AS state "
            "FROM deadlines d "
            "JOIN module_subscriptions s "
            "  ON s.module_id = d.module_id AND s.user_id = ? "
            "JOIN modules m ON m.id = d.module_id "
            "LEFT JOIN item_state st "
            "  ON st.deadline_id = d.id AND st.user_id = ? "
            "WHERE d.status = 'active' "
            "ORDER BY d.deadline",
            (user_id, user_id),
        ).fetchall()
        return [dict(r) for r in rows]


def set_status(user_id: int, deadline_id: int, status: str, at: str | None = None) -> None:
    completed_at = (at or _now()) if status == "completed" else None
    with _conn() as c:
        c.execute(
            "INSERT INTO item_state (user_id, deadline_id, status, completed_at) "
            "VALUES (?, ?, ?, ?) "
            "ON CONFLICT(user_id, deadline_id) DO UPDATE SET "
            "  status = excluded.status, completed_at = excluded.completed_at",
            (user_id, deadline_id, status, completed_at),
        )


def stats(user_id: int) -> dict:
    items = user_deadlines(user_id)
    total = len(items)
    completed = sum(1 for i in items if i["state"] == "completed")
    return {
        "total": total,
        "completed": completed,
        "pending": total - completed,
        "exams": sum(1 for i in items if i["type"] == "exam"),
        "homework": sum(1 for i in items if i["type"] == "homework"),
        "modules": len(user_modules(user_id)),
    }
