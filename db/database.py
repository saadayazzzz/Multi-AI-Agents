"""Postgres access helpers (psycopg 3, synchronous)."""
from __future__ import annotations

import contextlib
from pathlib import Path
from typing import Iterator

import psycopg
from psycopg.rows import dict_row

from config import settings

_SCHEMA = Path(__file__).with_name("schema.sql")


@contextlib.contextmanager
def get_conn() -> Iterator[psycopg.Connection]:
    """Yield a connection with dict rows; commits on clean exit, rolls back on error."""
    with psycopg.connect(settings.database_url, row_factory=dict_row) as conn:
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise


def init_db() -> None:
    """Create tables if they do not exist."""
    ddl = _SCHEMA.read_text(encoding="utf-8")
    with get_conn() as conn:
        conn.execute(ddl)
    print("db: schema ready")


def wait_for_db(timeout: float = 30.0) -> None:
    """Block until Postgres accepts connections (useful right after docker compose up)."""
    import time

    deadline = time.monotonic() + timeout
    last_err: Exception | None = None
    while time.monotonic() < deadline:
        try:
            with psycopg.connect(settings.database_url) as conn:
                conn.execute("SELECT 1")
            return
        except psycopg.OperationalError as e:  # noqa: PERF203
            last_err = e
            time.sleep(1.0)
    raise RuntimeError(f"database not reachable at {settings.database_url}: {last_err}")
