"""Background loop that keeps the sales engine running on its own.

    python -m sales.scheduler            # forever
    python -m sales.scheduler --once     # one pass (for cron / testing)

Each pass:
  - runs every source agent that is due (not paused, run_interval_minutes
    since its last run)
  - ticks every active campaign (only acts inside its active days / launch
    hour and seat caps - see sales/executor.py)
  - every 15 minutes, syncs the unibox (LinkedIn inbox + IMAP)
It honours JARVIS's power switch (system_state.power = 'off').
"""
from __future__ import annotations

import argparse
import time
import traceback

from db.database import get_conn, wait_for_db
from sales import emailer, executor, runner, unibox
from sales import linkedin as li
from sales.db import init_sales_db

INBOX_EVERY = 15 * 60
TICK_EVERY = 5 * 60


def _powered_off() -> bool:
    try:
        with get_conn() as conn:
            r = conn.execute("SELECT power FROM system_state WHERE id = 1").fetchone()
        return (r or {}).get("power") == "off"
    except Exception:  # noqa: BLE001
        return False


def sync_all_inboxes() -> dict:
    out = {}
    for seat in li.list_seats():
        if seat["has_session"]:
            try:
                out[f"linkedin:{seat['id']}"] = unibox.sync_linkedin(seat)
            except Exception as e:  # noqa: BLE001
                out[f"linkedin:{seat['id']}"] = {"error": str(e)[:200]}
    for s in emailer.list_seats():
        seat = emailer.get_seat(s["id"])
        if seat.get("imap_host"):
            try:
                out[f"email:{seat['id']}"] = emailer.sync_inbox(seat)
            except Exception as e:  # noqa: BLE001
                out[f"email:{seat['id']}"] = {"error": str(e)[:200]}
    return out


def run_pass(state: dict) -> dict:
    now = time.monotonic()
    result: dict = {"agents": [], "campaigns": [], "inbox": None}
    for agent_id in runner.due_agents():
        try:
            result["agents"].append(runner.run_agent(agent_id))
        except Exception as e:  # noqa: BLE001
            result["agents"].append({"agent_id": agent_id, "error": str(e)[:300]})
            traceback.print_exc()
    if now - state.get("last_tick", -1e9) >= TICK_EVERY:
        state["last_tick"] = now
        for cid in executor.active_campaign_ids():
            try:
                result["campaigns"].append(executor.tick(cid))
            except Exception as e:  # noqa: BLE001
                result["campaigns"].append({"campaign_id": cid, "error": str(e)[:300]})
                traceback.print_exc()
    if now - state.get("last_inbox", -1e9) >= INBOX_EVERY:
        state["last_inbox"] = now
        result["inbox"] = sync_all_inboxes()
    return result


def main() -> None:
    ap = argparse.ArgumentParser(prog="sales.scheduler")
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--poll", type=float, default=60.0)
    args = ap.parse_args()
    wait_for_db()
    init_sales_db()
    emailer.seat_from_env()
    state: dict = {}
    print("sales scheduler: online")
    while True:
        if _powered_off():
            time.sleep(args.poll)
            continue
        res = run_pass(state)
        if any(res.values()):
            print(f"sales scheduler: {res}")
        if args.once:
            return
        time.sleep(args.poll)


if __name__ == "__main__":
    main()
