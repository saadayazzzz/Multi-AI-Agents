"""Pipeline entry point.

    python orchestrator.py initdb          # create tables
    python orchestrator.py trends          # agent 1: trend scout
    python orchestrator.py content         # agent 2: content studio
    python orchestrator.py visuals         # agent 3: visual studio
    python orchestrator.py publish         # agent 4: publisher
    python orchestrator.py all             # 1 -> 2 -> 3 -> 4

    python orchestrator.py serve           # FastAPI control plane (for the console)
    python orchestrator.py worker          # autonomous task worker
"""
from __future__ import annotations

import argparse
import sys

# Windows consoles default to cp1252; agent output (— • ’   …) must not crash logging.
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from db import init_db
from db.database import wait_for_db


def main() -> int:
    parser = argparse.ArgumentParser(description="Autonomous viral-content marketing pipeline")
    parser.add_argument(
        "stage",
        choices=["initdb", "trends", "content", "visuals", "publish", "all", "serve", "worker"],
        help="which stage to run",
    )
    parser.add_argument("--platform", default=None, help="youtube | instagram | linkedin")
    parser.add_argument("--content-id", type=int, default=None, help="content piece id (visuals/publish)")
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

    if args.stage in ("initdb", "all", "trends", "content", "visuals", "publish"):
        init_db()
    if args.stage == "initdb":
        return 0

    if args.stage in ("trends", "all"):
        from agents.agent1_trends import scout

        print("\n=== Agent 1: trend scout ===")
        scout(args.platform)

    if args.stage in ("content", "all"):
        from agents.agent2_content import write

        print("\n=== Agent 2: content studio ===")
        write(args.platform or "linkedin")

    if args.stage in ("visuals", "all"):
        from agents.agent3_visuals import visualize

        print("\n=== Agent 3: visual studio ===")
        visualize(args.content_id)

    if args.stage in ("publish", "all"):
        from agents.agent4_publisher import publish
        from db import get_conn

        print("\n=== Agent 4: publisher ===")
        content_id = args.content_id
        if content_id is None:
            with get_conn() as conn:
                row = conn.execute(
                    "SELECT id FROM content_pieces WHERE status='ready' ORDER BY created_at DESC LIMIT 1"
                ).fetchone()
            content_id = row["id"] if row else None
        if content_id is None:
            print("no ready content to publish")
        else:
            publish(content_id)

    return 0


if __name__ == "__main__":
    sys.exit(main())
