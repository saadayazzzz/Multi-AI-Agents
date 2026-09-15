"""Ad Studio schema bootstrap.

The `ads` table lives in the core schema (db/schema.sql, alongside
market_feed) rather than a module-local schema.sql, since - like Agent 5 -
this is a single-table agent wired directly into the core orchestrator
rather than a whole gated subsystem (compare geo/, outreach/, studio/, which
each own several tables). init_ads_db() just re-runs the core init so the
Ad Studio also works from a standalone CLI invocation, before the server has
had a chance to run its own startup init.
"""
from __future__ import annotations

from db import init_db


def init_ads_db() -> None:
    init_db()
