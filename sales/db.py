"""Schema bootstrap + small row helpers shared by the sales engine."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from psycopg.types.json import Jsonb

from db.database import get_conn

_SCHEMA = Path(__file__).with_name("schema.sql")


def init_sales_db() -> None:
    """Apply outreach's schema first (source_agents/campaign_agents live
    there), then the sales tables + migrations on top."""
    from outreach.db import init_outreach_db

    init_outreach_db()
    with get_conn() as conn:
        conn.execute(_SCHEMA.read_text(encoding="utf-8"))


def jsonb(v: Any) -> Jsonb:
    return Jsonb(v)


def one(sql: str, params: tuple | list = ()) -> dict | None:
    with get_conn() as conn:
        return conn.execute(sql, params).fetchone()


def all_rows(sql: str, params: tuple | list = ()) -> list[dict]:
    with get_conn() as conn:
        return conn.execute(sql, params).fetchall()


def execute(sql: str, params: tuple | list = ()) -> None:
    with get_conn() as conn:
        conn.execute(sql, params)


def iso(row: dict | None) -> dict | None:
    """Datetimes/decimals -> JSON-friendly values for API responses."""
    if row is None:
        return None
    out = {}
    for k, v in row.items():
        if hasattr(v, "isoformat"):
            out[k] = v.isoformat()
        elif v.__class__.__name__ == "Decimal":
            out[k] = float(v)
        else:
            out[k] = v
    return out
