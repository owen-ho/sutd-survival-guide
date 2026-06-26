"""Live usage metrics for Agnes AI — the demo's proof that the LLM is the core.

Every Agnes call (routing each free-text message, plus date/offset parsing) is
recorded here: count, latency, token usage and an estimated cost. ``/agnes``
renders the running totals, which is the point we want judges to feel — the bot
calls a model on *every* message and it still costs fractions of a cent, because
the model is cheap and fast. Counters are process-local and reset on restart.
"""

import threading

from settings import AGNES_AI_MODEL, AGNES_AI_PRICE_PER_1M

_lock = threading.Lock()

calls = 0
errors = 0
total_latency_ms = 0.0
prompt_tokens = 0
completion_tokens = 0
by_task: dict[str, int] = {}  # e.g. {"route": 12, "parse_date": 3}


def record(task: str, latency_ms: float, usage: dict | None, ok: bool = True) -> None:
    """Record one Agnes call. ``usage`` is the API's token block, if present."""
    global calls, errors, total_latency_ms, prompt_tokens, completion_tokens
    with _lock:
        calls += 1
        by_task[task] = by_task.get(task, 0) + 1
        if not ok:
            errors += 1
            return  # a timed-out call's latency isn't representative — skip it
        total_latency_ms += latency_ms
        if usage:
            prompt_tokens += int(usage.get("prompt_tokens", 0) or 0)
            completion_tokens += int(usage.get("completion_tokens", 0) or 0)


def _est_cost() -> float:
    return (prompt_tokens + completion_tokens) / 1_000_000 * AGNES_AI_PRICE_PER_1M


def summary_text() -> str:
    with _lock:
        if calls == 0:
            return (
                "🤖 *Agnes AI — live usage*\n\n"
                "No calls yet this run. Just type a question like "
                "“how busy is the gym?” — Agnes routes every message you send."
            )
        ok_calls = calls - errors
        avg = total_latency_ms / ok_calls if ok_calls else 0
        tasks = ", ".join(f"{k} ×{v}" for k, v in sorted(by_task.items()))
        return (
            "🤖 *Agnes AI — live usage*\n\n"
            f"Model: `{AGNES_AI_MODEL}`\n"
            f"Calls: *{calls}* ({errors} failed)\n"
            f"Avg latency: *{avg:.0f} ms* (successful calls)\n"
            f"Tokens: {prompt_tokens:,} in + {completion_tokens:,} out\n"
            f"Est. cost: *${_est_cost():.5f}*\n\n"
            f"By task: {tasks}\n\n"
            "_Every message is an Agnes call — and it still costs a fraction of "
            "a cent. That's why cheap + fast lets the LLM be the core._"
        )
