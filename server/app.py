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

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field

from config import settings
from db import get_conn, init_db
from db.database import wait_for_db
from server import linkedin_oauth

app = FastAPI(title="JARVIS control plane")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in settings.cors_origins.split(",") if o.strip()],
    allow_methods=["*"],
    allow_headers=["*"],
)

_ACTORS = ["orchestrator", "agent5", "geo", "sales"]

# Sales engine (Gojiberry-equivalent): REST API + its own console at /sales.
from pathlib import Path  # noqa: E402

from fastapi.staticfiles import StaticFiles  # noqa: E402

from sales.api import router as sales_router  # noqa: E402

app.include_router(sales_router)
app.mount("/sales", StaticFiles(directory=str(Path(__file__).resolve().parent.parent / "sales" / "static"),
                                html=True), name="sales-console")


@app.on_event("startup")
def _startup() -> None:
    wait_for_db()
    init_db()
    # Otherwise only created lazily on first use - but the dashboard polls
    # their "latest" endpoints on load regardless, so create them up front.
    from geo.db import init_geo_db
    from outreach.db import init_outreach_db

    init_geo_db()
    init_outreach_db()
    from sales.db import init_sales_db

    init_sales_db()


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
        market_total = conn.execute("SELECT COUNT(*) n FROM market_feed").fetchone()["n"]
        # leads_by_status is keyed by the *latest* campaign only, matching
        # /api/outreach/latest - a brand-new console load shouldn't have to
        # wait on that separate request to show a non-zero lead count.
        camp = conn.execute("SELECT id FROM campaigns ORDER BY id DESC LIMIT 1").fetchone()
        leads_by_status: dict[str, int] = {}
        leads_total = 0
        if camp:
            rows = conn.execute(
                "SELECT status, COUNT(*) n FROM leads WHERE campaign_id = %s GROUP BY status",
                (camp["id"],),
            ).fetchall()
            leads_by_status = {r["status"]: r["n"] for r in rows}
            leads_total = sum(leads_by_status.values())
        pending = conn.execute(
            "SELECT COUNT(*) n FROM tasks WHERE status IN ('queued','running')"
        ).fetchone()["n"]
        power = conn.execute("SELECT power FROM system_state WHERE id = 1").fetchone()
    return {
        "market_total": market_total,
        "leads_by_status": leads_by_status,
        "leads_total": leads_total,
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


_MARKET_COLS = "id, ts, headline, detail, tag, sentiment, region, source"


def _market_after(cursor: int, limit: int = 50) -> list[dict[str, Any]]:
    with get_conn() as conn:
        rows = conn.execute(
            f"SELECT {_MARKET_COLS} FROM market_feed WHERE id > %s ORDER BY id LIMIT %s",
            (cursor, limit),
        ).fetchall()
    return [_iso(r) for r in rows]


def _recent_market(n: int = 14) -> list[dict[str, Any]]:
    with get_conn() as conn:
        rows = conn.execute(
            f"SELECT {_MARKET_COLS} FROM market_feed ORDER BY id DESC LIMIT %s", (n,)
        ).fetchall()
    return [_iso(r) for r in reversed(rows)]


def _max_market_id() -> int:
    with get_conn() as conn:
        row = conn.execute("SELECT COALESCE(MAX(id), 0) m FROM market_feed").fetchone()
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


@app.get("/api/market")
async def market(limit: int = 30) -> list[dict[str, Any]]:
    return await run_in_threadpool(_recent_market, min(limit, 100))


# --------------------------------------------------------------------------- #
# LinkedIn "Connect" (official OAuth - see server/linkedin_oauth.py)
# --------------------------------------------------------------------------- #
def _frontend_url() -> str:
    first = settings.cors_origins.split(",")[0].strip()
    return first or "http://localhost:3737"


@app.get("/api/linkedin/status")
async def linkedin_status() -> dict[str, Any]:
    return await run_in_threadpool(linkedin_oauth.status)


@app.get("/api/linkedin/login")
async def linkedin_login() -> RedirectResponse:
    try:
        url = await run_in_threadpool(linkedin_oauth.authorize_url)
    except RuntimeError as e:
        raise HTTPException(400, str(e))
    return RedirectResponse(url)


@app.get("/api/linkedin/callback")
async def linkedin_callback(code: str | None = None, state: str | None = None, error: str | None = None) -> RedirectResponse:
    if error or not code or not state:
        return RedirectResponse(f"{_frontend_url()}/?linkedin=error")
    try:
        await run_in_threadpool(linkedin_oauth.complete_callback, code, state)
    except Exception:
        return RedirectResponse(f"{_frontend_url()}/?linkedin=error")
    return RedirectResponse(f"{_frontend_url()}/?linkedin=connected")


@app.post("/api/linkedin/disconnect")
async def linkedin_disconnect() -> dict[str, str]:
    await run_in_threadpool(linkedin_oauth.disconnect)
    return {"status": "disconnected"}


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
            SELECT id, company, domain, contact_name, contact_role, contact_email,
                   email_status, linkedin_url, linkedin_activity, trigger,
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


@app.websocket("/ws")
async def ws(sock: WebSocket) -> None:
    await sock.accept()
    cursor = await run_in_threadpool(_max_event_id)
    market_cursor = 0
    tick = 0
    try:
        await sock.send_text(json.dumps({
            "type": "snapshot",
            "stats": await run_in_threadpool(_stats),
            "agents": await run_in_threadpool(_agents),
            "tasks": await run_in_threadpool(_tasks, 40),
            "market": await run_in_threadpool(_recent_market, 14),
        }))
        market_cursor = await run_in_threadpool(_max_market_id)
        while True:
            events = await run_in_threadpool(_events_after, cursor)
            if events:
                cursor = events[-1]["id"]
                await sock.send_text(json.dumps({"type": "events", "events": events}))

            market_items = await run_in_threadpool(_market_after, market_cursor)
            if market_items:
                market_cursor = market_items[-1]["id"]
                await sock.send_text(json.dumps({"type": "market", "items": market_items}))

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
