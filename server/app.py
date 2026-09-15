"""FastAPI control plane for the JARVIS console.

The browser talks only to this API. This API talks only to Postgres. The worker
(server/worker.py) is a separate process that also talks only to Postgres, so
tasks keep running whether or not the console is open.

    uvicorn server.app:app --host 127.0.0.1 --port 8000
"""
from __future__ import annotations

import asyncio
import json
from decimal import Decimal
from typing import Any

from pathlib import Path

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
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

_ACTORS = ["orchestrator", "agent1", "agent2", "agent3", "agent4", "agent5",
           "geo", "sales", "studio", "ads"]

_content_dir = Path(settings.output_dir) / "content"
_content_dir.mkdir(parents=True, exist_ok=True)
app.mount("/img/content", StaticFiles(directory=str(_content_dir)), name="content-images")

# Rendered videos - one subfolder per row (output/<kind>/<id>/final.mp4 etc.),
# served so the dashboard can play them in-place instead of only linking out
# to YouTube once uploaded.
for _kind in ("ads", "videos"):
    _dir = Path(settings.output_dir) / _kind
    _dir.mkdir(parents=True, exist_ok=True)
    app.mount(f"/media/{_kind}", StaticFiles(directory=str(_dir)), name=f"{_kind}-media")


@app.on_event("startup")
def _startup() -> None:
    wait_for_db()
    init_db()


# --------------------------------------------------------------------------- #
# sync DB helpers (run in a threadpool from async routes)
# --------------------------------------------------------------------------- #
def _power() -> str:
    with get_conn() as conn:
        row = conn.execute("SELECT power FROM system_state WHERE id = 1").fetchone()
    return (row or {}).get("power", "on")


def _set_power(state: str) -> dict[str, str]:
    with get_conn() as conn:
        conn.execute(
            "UPDATE system_state SET power = %s, updated_at = now() WHERE id = 1", (state,)
        )
    return {"power": state}


def _stats() -> dict[str, Any]:
    with get_conn() as conn:
        trends = conn.execute(
            "SELECT platform, COUNT(*) n FROM trends WHERE status='new' GROUP BY platform"
        ).fetchall()
        content_by_status = conn.execute(
            "SELECT status, COUNT(*) n FROM content_pieces GROUP BY status"
        ).fetchall()
        content_total = conn.execute("SELECT COUNT(*) n FROM content_pieces").fetchone()["n"]
        posted_by_platform = conn.execute(
            "SELECT platform, COUNT(*) n FROM content_pieces WHERE status='posted' GROUP BY platform"
        ).fetchall()
        pending = conn.execute(
            "SELECT COUNT(*) n FROM tasks WHERE status IN ('queued','running')"
        ).fetchone()["n"]
        power = conn.execute("SELECT power FROM system_state WHERE id = 1").fetchone()
    return {
        "trends": {r["platform"]: r["n"] for r in trends},
        "trends_total": sum(r["n"] for r in trends),
        "content_by_status": {r["status"]: r["n"] for r in content_by_status},
        "content_total": content_total,
        "posted_by_platform": {r["platform"]: r["n"] for r in posted_by_platform},
        "tasks_pending": pending,
        "power": (power or {}).get("power", "on"),
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


def _content(limit: int) -> list[dict[str, Any]]:
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT c.id, c.platform, c.title, c.script, c.caption, c.cta,
                   c.hashtags, c.status, c.external_url, c.error,
                   c.created_at, c.posted_at, i.rel_path AS image_rel_path
            FROM content_pieces c
            LEFT JOIN content_images i ON i.content_id = c.id
            ORDER BY c.created_at DESC LIMIT %s
            """,
            (limit,),
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


_TREND_COLS = "id, platform, topic, angle, format, score, source, created_at AS ts"


def _trends_after(cursor: int, limit: int = 50) -> list[dict[str, Any]]:
    with get_conn() as conn:
        rows = conn.execute(
            f"SELECT {_TREND_COLS} FROM trends WHERE id > %s ORDER BY id LIMIT %s",
            (cursor, limit),
        ).fetchall()
    return [_iso(r) for r in rows]


def _recent_trends(n: int = 14) -> list[dict[str, Any]]:
    with get_conn() as conn:
        rows = conn.execute(
            f"SELECT {_TREND_COLS} FROM trends ORDER BY id DESC LIMIT %s", (n,)
        ).fetchall()
    return [_iso(r) for r in reversed(rows)]


def _max_trend_id() -> int:
    with get_conn() as conn:
        row = conn.execute("SELECT COALESCE(MAX(id), 0) m FROM trends").fetchone()
    return row["m"]


def _iso(row: dict[str, Any]) -> dict[str, Any]:
    out = dict(row)
    for k, v in list(out.items()):
        if hasattr(v, "isoformat"):
            out[k] = v.isoformat()
        elif isinstance(v, Decimal):
            out[k] = float(v)
    return out


# --------------------------------------------------------------------------- #
# routes
# --------------------------------------------------------------------------- #
class TaskIn(BaseModel):
    prompt: str = Field(min_length=1, max_length=4000)
    source: str = "voice"


class PowerIn(BaseModel):
    state: str  # "on" | "off"


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


@app.get("/api/trends")
async def trends(limit: int = 30) -> list[dict[str, Any]]:
    return await run_in_threadpool(_recent_trends, min(limit, 100))


def _geo_latest() -> dict[str, Any] | None:
    with get_conn() as conn:
        sc = conn.execute(
            """
            SELECT s.*, p.brand, p.domain, p.competitors
            FROM visibility_scores s JOIN projects p ON p.id = s.project_id
            ORDER BY s.id DESC LIMIT 1
            """
        ).fetchone()
        if not sc:
            return None
        rows = conn.execute(
            """
            SELECT q.text, q.intent, pr.brand_mentioned, pr.brand_position,
                   pr.brand_recommended, pr.sentiment, pr.competitor_mentions
            FROM probes pr JOIN queries q ON q.id = pr.query_id
            WHERE pr.run_id = %s ORDER BY pr.id
            """,
            (sc["run_id"],),
        ).fetchall()
    return {"score": _iso(sc), "queries": [_iso(r) for r in rows]}


@app.get("/api/geo/latest")
async def geo_latest() -> dict[str, Any] | None:
    return await run_in_threadpool(_geo_latest)


def _outreach_latest() -> dict[str, Any] | None:
    with get_conn() as conn:
        camp = conn.execute("SELECT * FROM campaigns ORDER BY id DESC LIMIT 1").fetchone()
        if not camp:
            return None
        leads = conn.execute(
            """
            SELECT id, company, domain, contact_role, contact_email, email_status,
                   icp_fit, geo_score, geo_finding, status
            FROM leads WHERE campaign_id = %s ORDER BY id DESC LIMIT 40
            """,
            (camp["id"],),
        ).fetchall()
        counts = {
            r["status"]: r["n"]
            for r in conn.execute(
                "SELECT status, COUNT(*) n FROM leads WHERE campaign_id = %s GROUP BY status",
                (camp["id"],),
            ).fetchall()
        }
        sample = conn.execute(
            """
            SELECT l.company, m.subject, m.body
            FROM messages m JOIN leads l ON l.id = m.lead_id
            WHERE l.campaign_id = %s AND m.step = 1 ORDER BY m.id DESC LIMIT 1
            """,
            (camp["id"],),
        ).fetchone()
    return {
        "campaign": _iso(camp),
        "counts": counts,
        "total": sum(counts.values()),
        "leads": [_iso(r) for r in leads],
        "sample": _iso(sample) if sample else None,
    }


@app.get("/api/outreach/latest")
async def outreach_latest() -> dict[str, Any] | None:
    return await run_in_threadpool(_outreach_latest)


def _studio_recent(n: int = 8) -> list[dict[str, Any]]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT id, theme, title, clip_count, seconds, privacy, status, "
            "youtube_url, created_at FROM videos ORDER BY id DESC LIMIT %s",
            (n,),
        ).fetchall()
    return [_iso(r) for r in rows]


@app.get("/api/studio/recent")
async def studio_recent() -> list[dict[str, Any]]:
    return await run_in_threadpool(_studio_recent)


def _ads_recent(n: int = 8) -> list[dict[str, Any]]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT id, niche, product, hook, seconds, privacy, status, "
            "youtube_url, created_at FROM ads ORDER BY id DESC LIMIT %s",
            (n,),
        ).fetchall()
    return [_iso(r) for r in rows]


@app.get("/api/ads/recent")
async def ads_recent() -> list[dict[str, Any]]:
    return await run_in_threadpool(_ads_recent)


@app.post("/api/tasks", status_code=201)
async def create_task(body: TaskIn) -> dict[str, Any]:
    if await run_in_threadpool(_power) == "off":
        raise HTTPException(409, "JARVIS is powered down")
    return await run_in_threadpool(_create_task, body.prompt.strip(), body.source)


@app.post("/api/power")
async def power(body: PowerIn) -> dict[str, str]:
    if body.state not in ("on", "off"):
        raise HTTPException(400, "state must be 'on' or 'off'")
    return await run_in_threadpool(_set_power, body.state)


@app.get("/api/tasks/{task_id}")
async def task_detail(task_id: int) -> dict[str, Any]:
    return await run_in_threadpool(_task_detail, task_id)


@app.post("/api/tasks/{task_id}/cancel")
async def cancel_task(task_id: int) -> dict[str, Any]:
    return await run_in_threadpool(_cancel_task, task_id)


@app.get("/api/content")
async def content(limit: int = 40) -> list[dict[str, Any]]:
    return await run_in_threadpool(_content, min(limit, 200))


@app.post("/api/content/{content_id}/approve")
async def approve_content(content_id: int) -> dict[str, Any]:
    if await run_in_threadpool(_power) == "off":
        raise HTTPException(409, "JARVIS is powered down")
    from agents.agent4_publisher import publish

    return await run_in_threadpool(publish, content_id)


@app.websocket("/ws")
async def ws(sock: WebSocket) -> None:
    await sock.accept()
    cursor = await run_in_threadpool(_max_event_id)
    trend_cursor = 0
    tick = 0
    try:
        await sock.send_text(json.dumps({
            "type": "snapshot",
            "stats": await run_in_threadpool(_stats),
            "agents": await run_in_threadpool(_agents),
            "tasks": await run_in_threadpool(_tasks, 40),
            "trends": await run_in_threadpool(_recent_trends, 14),
        }))
        trend_cursor = await run_in_threadpool(_max_trend_id)
        while True:
            events = await run_in_threadpool(_events_after, cursor)
            if events:
                cursor = events[-1]["id"]
                await sock.send_text(json.dumps({"type": "events", "events": events}))

            trend_items = await run_in_threadpool(_trends_after, trend_cursor)
            if trend_items:
                trend_cursor = trend_items[-1]["id"]
                await sock.send_text(json.dumps({"type": "trends", "items": trend_items}))

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
