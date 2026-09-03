"""Autonomous worker.

Runs as its own process. Claims queued tasks from Postgres one at a time, hands
each to the JARVIS orchestrator, streams progress into `task_events`, and
re-enqueues recurring tasks. Keeps running whether or not the console is open.

    python -m server.worker
"""
from __future__ import annotations

import signal
import time

from psycopg.types.json import Jsonb

from config import settings
from db import init_db, get_conn
from db.database import wait_for_db
from server.brain import run_task

_running = True


def _stop(*_):
    global _running
    _running = False
    print("worker: shutting down after current task")


def emit(task_id: int, actor: str, kind: str, message: str, data: dict | None = None) -> None:
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO task_events (task_id, actor, kind, message, data) "
            "VALUES (%s, %s, %s, %s, %s)",
            (task_id, actor, kind, message, Jsonb(data or {})),
        )


def _claim_task() -> dict | None:
    """Atomically move the next eligible task to 'running'."""
    with get_conn() as conn:
        return conn.execute(
            """
            UPDATE tasks SET status = 'running', started_at = now()
            WHERE id = (
                SELECT id FROM tasks
                WHERE status = 'queued' AND run_after <= now()
                ORDER BY priority, run_after, id
                FOR UPDATE SKIP LOCKED
                LIMIT 1
            )
            RETURNING id, prompt, source, recur_seconds
            """
        ).fetchone()


def _finish(task: dict, status: str, summary: str, spoken: str, error: str | None) -> None:
    with get_conn() as conn:
        conn.execute(
            "UPDATE tasks SET status = %s, result_summary = %s, spoken_response = %s, "
            "error = %s, finished_at = now() WHERE id = %s",
            (status, summary, spoken, error, task["id"]),
        )
        if task["recur_seconds"] and status == "done":
            conn.execute(
                "INSERT INTO tasks (prompt, source, recur_seconds, run_after) "
                "VALUES (%s, %s, %s, now() + (%s || ' seconds')::interval)",
                (task["prompt"], task["source"], task["recur_seconds"], task["recur_seconds"]),
            )


def run() -> None:
    for sig in ("SIGINT", "SIGTERM", "SIGBREAK"):
        s = getattr(signal, sig, None)
        if s is not None:
            try:
                signal.signal(s, _stop)
            except (ValueError, OSError):
                pass

    wait_for_db()
    init_db()
    print(f"worker: online, polling every {settings.worker_poll_seconds}s")

    while _running:
        task = _claim_task()
        if task is None:
            time.sleep(settings.worker_poll_seconds)
            continue

        print(f"worker: task {task['id']}  {task['prompt'][:80]!r}")
        emit(task["id"], "system", "status", "Task started", {"prompt": task["prompt"]})
        try:
            summary, spoken = run_task(task["id"], task["prompt"], _bind_emit(task["id"]))
            _finish(task, "done", summary, spoken, None)
            emit(task["id"], "system", "spoken", spoken, {})
            emit(task["id"], "system", "status", "Task complete", {})
        except Exception as e:  # noqa: BLE001
            msg = f"{type(e).__name__}: {e}"
            _finish(task, "failed", "", "Something went wrong.", msg)
            emit(task["id"], "system", "error", msg, {})
            print(f"worker: task {task['id']} failed: {msg}")


def _bind_emit(task_id: int):
    def _e(actor: str, kind: str, message: str, data: dict) -> None:
        emit(task_id, actor, kind, message, data)

    return _e


if __name__ == "__main__":
    run()
