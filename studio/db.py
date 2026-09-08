"""Studio schema bootstrap (shares the project Postgres)."""
from __future__ import annotations

from pathlib import Path

from db.database import get_conn

_SCHEMA = Path(__file__).with_name("schema.sql")


def init_studio_db() -> None:
    with get_conn() as conn:
        conn.execute(_SCHEMA.read_text(encoding="utf-8"))
    print("studio: schema ready")
