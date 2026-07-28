import asyncio
import json
import logging
import sqlite3
import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Request

logger = logging.getLogger("infotainment_agent.protocol")

router = APIRouter(tags=["Agent Protocol"])

# ── Database (in-memory SQLite, shared across the process) ────────────────

_conn = sqlite3.connect(":memory:", check_same_thread=False)
_conn.row_factory = sqlite3.Row


def _init_db() -> None:
    _conn.executescript("""
        CREATE TABLE IF NOT EXISTS threads (
            thread_id  TEXT PRIMARY KEY,
            created_at TEXT NOT NULL,
            messages   TEXT NOT NULL DEFAULT '[]',
            values_    TEXT NOT NULL DEFAULT '{}'
        );
        CREATE TABLE IF NOT EXISTS runs (
            run_id       TEXT PRIMARY KEY,
            thread_id    TEXT NOT NULL REFERENCES threads(thread_id),
            assistant_id TEXT NOT NULL,
            status       TEXT NOT NULL DEFAULT 'pending',
            created_at   TEXT NOT NULL,
            error        TEXT
        );
    """)
    _conn.commit()


_init_db()

# ── DB helpers ──────────────────────────────────────────────────────────────


def _get_thread(thread_id: str) -> dict[str, Any] | None:
    row = _conn.execute(
        "SELECT thread_id, created_at, messages, values_ FROM threads WHERE thread_id = ?",
        (thread_id,),
    ).fetchone()
    if row is None:
        return None
    return {
        "thread_id": row["thread_id"],
        "created_at": row["created_at"],
        "messages": json.loads(row["messages"]),
        "values": json.loads(row["values_"]),
    }


def _get_run(run_id: str) -> dict[str, Any] | None:
    row = _conn.execute(
        "SELECT run_id, thread_id, assistant_id, status, created_at, error FROM runs WHERE run_id = ?",
        (run_id,),
    ).fetchone()
    if row is None:
        return None
    return dict(row)


# ── Agent invocation ──────────────────────────────────────────────────────
#
# TODO: wire this to your actual InfotainmentAgentExecutor / underlying model.
# The only contract required by the Agent Protocol callers is:
#   input:  a user message string
#   output: a string (the assistant's final reply)
#
# If InfotainmentAgentExecutor exposes an async method like `.invoke(message)`
# or `.execute(message)`, call it here instead of the stub below.

async def _invoke_infotainment_agent(user_message: str) -> str:
    try:
        from agent_executor import InfotainmentAgentExecutor  # local import to avoid cycles

        executor = InfotainmentAgentExecutor()
        result = await executor.run(user_message)  # returns a dict
        return json.dumps(result)

    except Exception:
        logger.error("Failed to invoke infotainment agent", exc_info=True)
        raise


# ── Run executor ──────────────────────────────────────────────────────────


async def _execute_run(run_id: str, thread_id: str, user_message: str) -> None:
    _conn.execute("UPDATE runs SET status = 'running' WHERE run_id = ?", (run_id,))
    _conn.commit()
    try:
        output = await _invoke_infotainment_agent(user_message)
        assistant_msg = {"role": "assistant", "content": output}

        row = _conn.execute(
            "SELECT messages FROM threads WHERE thread_id = ?", (thread_id,)
        ).fetchone()
        msgs = json.loads(row[0]) if row else []
        msgs.append(assistant_msg)

        _conn.execute(
            "UPDATE threads SET messages = ?, values_ = ? WHERE thread_id = ?",
            (json.dumps(msgs), json.dumps({"messages": msgs}), thread_id),
        )
        _conn.execute("UPDATE runs SET status = 'success' WHERE run_id = ?", (run_id,))
        _conn.commit()
    except Exception as exc:  # noqa: BLE001
        _conn.execute(
            "UPDATE runs SET status = 'error', error = ? WHERE run_id = ?",
            (str(exc), run_id),
        )
        _conn.commit()


# ── Routes ──────────────────────────────────────────────────────────────────


@router.get("/ok")
async def health() -> dict[str, bool]:
    """Health check."""
    return {"ok": True}


@router.post("/threads")
async def create_thread() -> dict[str, Any]:
    """Create a thread. Called by start_async_task before creating a run."""
    thread_id = str(uuid.uuid4())
    now = datetime.now(UTC).isoformat()
    _conn.execute(
        "INSERT INTO threads (thread_id, created_at) VALUES (?, ?)",
        (thread_id, now),
    )
    _conn.commit()
    return {"thread_id": thread_id, "created_at": now, "messages": [], "values": {}}


@router.post("/threads/{thread_id}/runs")
async def create_run(thread_id: str, request: Request) -> dict[str, Any]:
    """Create a run on an existing thread.

    Called by both start_async_task (new task) and update_async_task
    (re-run with new instructions). When multitask_strategy is 'interrupt',
    any currently-running runs on the thread are cancelled and the thread
    state is cleared before the new run starts.
    """
    thread = _get_thread(thread_id)
    if thread is None:
        raise HTTPException(status_code=404, detail="Thread not found")

    body = await request.json()
    multitask_strategy = body.get("multitask_strategy")

    if multitask_strategy == "interrupt":
        _conn.execute(
            "UPDATE runs SET status = 'cancelled' WHERE thread_id = ? AND status = 'running'",
            (thread_id,),
        )
        _conn.execute(
            "UPDATE threads SET values_ = '{}' WHERE thread_id = ?",
            (thread_id,),
        )
        _conn.commit()

    messages = (body.get("input") or {}).get("messages") or []
    user_message = next((m["content"] for m in messages if m.get("role") == "user"), "")

    if user_message:
        existing = json.loads(
            _conn.execute(
                "SELECT messages FROM threads WHERE thread_id = ?", (thread_id,)
            ).fetchone()[0]
        )
        existing.append({"role": "user", "content": user_message})
        _conn.execute(
            "UPDATE threads SET messages = ? WHERE thread_id = ?",
            (json.dumps(existing), thread_id),
        )
        _conn.commit()

    run_id = str(uuid.uuid4())
    now = datetime.now(UTC).isoformat()
    assistant_id = body.get("assistant_id") or "infotainment"
    _conn.execute(
        "INSERT INTO runs (run_id, thread_id, assistant_id, created_at) VALUES (?, ?, ?, ?)",
        (run_id, thread_id, assistant_id, now),
    )
    _conn.commit()

    # Fire and forget — client polls GET /threads/{thread_id}/runs/{run_id} for status.
    asyncio.ensure_future(_execute_run(run_id, thread_id, user_message))

    return {
        "run_id": run_id,
        "thread_id": thread_id,
        "assistant_id": assistant_id,
        "status": "pending",
        "created_at": now,
        "error": None,
    }


@router.get("/threads/{thread_id}/runs/{run_id}")
async def get_run(thread_id: str, run_id: str) -> dict[str, Any]:
    """Get run status. Called by check_async_task to poll whether a task has finished."""
    run = _get_run(run_id)
    if run is None or run["thread_id"] != thread_id:
        raise HTTPException(status_code=404, detail="Run not found")
    return run


@router.get("/threads/{thread_id}")
async def get_thread(thread_id: str) -> dict[str, Any]:
    """Get thread state. Called by check_async_task after a run reaches 'success' status.

    The SDK reads values['messages'] to extract the final result.
    """
    thread = _get_thread(thread_id)
    if thread is None:
        raise HTTPException(status_code=404, detail="Thread not found")
    return thread


@router.post("/threads/{thread_id}/runs/{run_id}/cancel")
async def cancel_run(thread_id: str, run_id: str) -> dict[str, Any]:
    """Cancel a run. Called by cancel_async_task."""
    run = _get_run(run_id)
    if run is None or run["thread_id"] != thread_id:
        raise HTTPException(status_code=404, detail="Run not found")
    _conn.execute("UPDATE runs SET status = 'cancelled' WHERE run_id = ?", (run_id,))
    _conn.commit()
    return {**run, "status": "cancelled"}