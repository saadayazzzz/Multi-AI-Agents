"""FastAPI control plane for the JARVIS console.

The browser talks only to this API. This API talks only to Postgres. The worker
(server/worker.py) is a separate process that also talks only to Postgres, so
tasks keep running whether or not the console is open.

    uvicorn server.app:app --host 127.0.0.1 --port 8000
"""
from __future__ import annotations

import asyncio
import json
from typing import Any

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from config import settings
from db import get_conn, init_db
from db.database import wait_for_db

app = FastAPI(title="JARVIS control plane")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in settings.cors_origins.split(",") if o.strip()],
    allow_methods=["*"],
    allow_headers=["*"],
)

_ACTORS = ["orchestrator", "agent1", "agent2", "agent3", "agent4"]


@app.on_event("startup")
def _startup() -> None:
    wait_for_db()
    init_db()


# --------------------------------------------------------------------------- #
# sync DB helpers (run in a threadpool from async routes)
# --------------------------------------------------------------------------- #
def _stats() -> dict[str, Any]:
    with get_conn() as conn:
        sites = conn.execute(
            "SELECT status, COUNT(*) n FROM sites GROUP BY status"
        ).fetchall()
        products = conn.execute("SELECT COUNT(*) n FROM products").fetchone()["n"]
        brands = conn.execute("SELECT COUNT(*) n FROM generated_brand").fetchone()["n"]
        pending = conn.execute(
            "SELECT COUNT(*) n FROM tasks WHERE status IN ('queued','running')"
        ).fetchone()["n"]
    return {
        "sites": {r["status"]: r["n"] for r in sites},
        "sites_total": sum(r["n"] for r in sites),
        "products": products,
        "brands": brands,
        "tasks_pending": pending,
    }


def _agents() -> list[dict[str, Any]]:
    out = []
    with get_conn() as conn:
        running = conn.execute(
            "SELECT COUNT(*) n FROM tasks WHERE status = 'running'"
        ).fetchone()["n"]
        for actor in _ACTORS:
            row = conn.execute(
                "SELECT message, kind, ts FROM task_events WHERE actor = %s "
                "ORDER BY id DESC LIMIT 1",
                (actor,),
            ).fetchone()
            out.append({
                "actor": actor,
                "state": "working" if running else "idle",
                "last_message": row["message"] if row else None,
                "last_kind": row["kind"] if row else None,
                "last_ts": row["ts"].isoformat() if row else None,
            })
    return out


def _tasks(limit: int) -> list[dict[str, Any]]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT id, prompt, source, status, recur_seconds, result_summary, "
            "spoken_response, error, created_at, started_at, finished_at "
            "FROM tasks ORDER BY id DESC LIMIT %s",
            (limit,),
        ).fetchall()
    return [_iso(r) for r in rows]


def _task_detail(task_id: int) -> dict[str, Any]:
    with get_conn() as conn:
        task = conn.execute("SELECT * FROM tasks WHERE id = %s", (task_id,)).fetchone()
        if not task:
            raise HTTPException(404, "task not found")
        events = conn.execute(
            "SELECT id, actor, kind, message, data, ts FROM task_events "
            "WHERE task_id = %s ORDER BY id",
            (task_id,),
        ).fetchall()
    return {"task": _iso(task), "events": [_iso(e) for e in events]}


def _create_task(prompt: str, source: str) -> dict[str, Any]:
    with get_conn() as conn:
        row = conn.execute(
            "INSERT INTO tasks (prompt, source) VALUES (%s, %s) "
            "RETURNING id, prompt, source, status, created_at",
            (prompt, source),
        ).fetchone()
    return _iso(row)


def _cancel_task(task_id: int) -> dict[str, Any]:
    with get_conn() as conn:
        row = conn.execute(
            "UPDATE tasks SET status = 'cancelled', finished_at = now() "
            "WHERE id = %s AND status = 'queued' RETURNING id, status",
            (task_id,),
        ).fetchone()
    if not row:
        raise HTTPException(409, "task not queued")
    return _iso(row)


def _brands() -> list[dict[str, Any]]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT slug, spec, output_path, created_at FROM generated_brand "
            "ORDER BY created_at DESC"
        ).fetchall()
    return [_iso(r) for r in rows]


def _events_after(cursor: int, limit: int = 300) -> list[dict[str, Any]]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT id, task_id, actor, kind, message, data, ts FROM task_events "
            "WHERE id > %s ORDER BY id LIMIT %s",
            (cursor, limit),
        ).fetchall()
    return [_iso(r) for r in rows]


def _max_event_id() -> int:
    with get_conn() as conn:
        row = conn.execute("SELECT COALESCE(MAX(id), 0) m FROM task_events").fetchone()
    return row["m"]


def _iso(row: dict[str, Any]) -> dict[str, Any]:
    out = dict(row)
    for k, v in list(out.items()):
        if hasattr(v, "isoformat"):
            out[k] = v.isoformat()
    return out


# --------------------------------------------------------------------------- #
# routes
# --------------------------------------------------------------------------- #
class TaskIn(BaseModel):
    prompt: str = Field(min_length=1, max_length=4000)
    source: str = "voice"


@app.get("/api/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/stats")
async def stats() -> dict[str, Any]:
    return await run_in_threadpool(_stats)


@app.get("/api/agents")
async def agents() -> list[dict[str, Any]]:
    return await run_in_threadpool(_agents)


@app.get("/api/tasks")
async def list_tasks(limit: int = 40) -> list[dict[str, Any]]:
    return await run_in_threadpool(_tasks, min(limit, 200))


@app.post("/api/tasks", status_code=201)
async def create_task(body: TaskIn) -> dict[str, Any]:
    return await run_in_threadpool(_create_task, body.prompt.strip(), body.source)


@app.get("/api/tasks/{task_id}")
async def task_detail(task_id: int) -> dict[str, Any]:
    return await run_in_threadpool(_task_detail, task_id)


@app.post("/api/tasks/{task_id}/cancel")
async def cancel_task(task_id: int) -> dict[str, Any]:
    return await run_in_threadpool(_cancel_task, task_id)


@app.get("/api/brands")
async def brands() -> list[dict[str, Any]]:
    return await run_in_threadpool(_brands)


@app.websocket("/ws")
async def ws(sock: WebSocket) -> None:
    await sock.accept()
    cursor = await run_in_threadpool(_max_event_id)
    tick = 0
    try:
        # initial snapshot
        await sock.send_text(json.dumps({
            "type": "snapshot",
            "stats": await run_in_threadpool(_stats),
            "agents": await run_in_threadpool(_agents),
            "tasks": await run_in_threadpool(_tasks, 40),
        }))
        while True:
            events = await run_in_threadpool(_events_after, cursor)
            if events:
                cursor = events[-1]["id"]
                await sock.send_text(json.dumps({"type": "events", "events": events}))
            tick += 1
            if tick % 4 == 0:  # ~ every 2s
                await sock.send_text(json.dumps({
                    "type": "snapshot",
                    "stats": await run_in_threadpool(_stats),
                    "agents": await run_in_threadpool(_agents),
                    "tasks": await run_in_threadpool(_tasks, 40),
                }))
            await asyncio.sleep(0.5)
    except WebSocketDisconnect:
        return
    except Exception:
        await sock.close()
