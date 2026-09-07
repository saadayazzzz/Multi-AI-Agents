"""Pipeline entry point.

    python orchestrator.py initdb          # create tables
    python orchestrator.py discover        # agent 1
    python orchestrator.py scrape          # agent 2
    python orchestrator.py build           # agent 3
    python orchestrator.py all             # 1 -> 2 -> 3

    python orchestrator.py serve           # FastAPI control plane (for the console)
    python orchestrator.py worker          # autonomous task worker
"""
from __future__ import annotations

import argparse
import sys

# Windows consoles default to cp1252; agent output (— • ’   …) must not crash logging.
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from db import init_db
from db.database import wait_for_db


def main() -> int:
    parser = argparse.ArgumentParser(description="Multi-agent skincare/cosmetics pipeline")
    parser.add_argument(
        "stage",
        choices=["initdb", "discover", "scrape", "build", "all", "serve", "worker"],
        help="which stage to run",
    )
    parser.add_argument("--limit", type=int, default=None, help="max sites for scrape")
    args = parser.parse_args()

    if args.stage == "serve":
        import uvicorn

        from config import settings

        uvicorn.run(
            "server.app:app", host=settings.server_host, port=settings.server_port
        )
        return 0

    if args.stage == "worker":
        from server.worker import run as run_worker

        run_worker()
        return 0

    wait_for_db()

    if args.stage in ("initdb", "all", "discover", "scrape", "build"):
        init_db()
    if args.stage == "initdb":
        return 0

    if args.stage in ("discover", "all"):
        from agents.agent1_discovery import discover

        print("\n=== Agent 1: discovery ===")
        discover()

    if args.stage in ("scrape", "all"):
        from agents.agent2_scraper import scrape

        print("\n=== Agent 2: scrape & store ===")
        scrape(limit=args.limit)

    if args.stage in ("build", "all"):
        from agents.agent3_brand_builder import build

        print("\n=== Agent 3: brand + site ===")
        build()

    return 0


if __name__ == "__main__":
    sys.exit(main())
