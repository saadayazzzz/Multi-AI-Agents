"""Test setup: a throwaway Postgres database and a stubbed LLM.

Needs a reachable Postgres (TEST_DATABASE_URL, default
postgresql://maai:maai@127.0.0.1:5432/maai_test); DB tests skip otherwise.
The LLM module is replaced with a stub so tests never call a model or the
network - each test installs the canned answers it needs.
"""
from __future__ import annotations

import os
import sys
import types

TEST_DB = os.environ.get("TEST_DATABASE_URL", "postgresql://maai:maai@127.0.0.1:5432/maai_test")
os.environ["DATABASE_URL"] = TEST_DB
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest  # noqa: E402

_llm = types.ModuleType("agents.llm")


def _unset(*_a, **_k):
    raise RuntimeError("LLM not stubbed in this test")


_llm.json_out = _unset
_llm.research = lambda *a, **k: ""
_llm.generate_text = _unset
sys.modules["agents.llm"] = _llm


def _db_available() -> bool:
    import psycopg

    base, name = TEST_DB.rsplit("/", 1)
    try:
        with psycopg.connect(base + "/postgres", autocommit=True, connect_timeout=3) as c:
            c.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
            c.execute(f'CREATE DATABASE "{name}"')
        return True
    except Exception:  # noqa: BLE001
        return False


DB_OK = _db_available()


@pytest.fixture(scope="session")
def db():
    if not DB_OK:
        pytest.skip("no Postgres for tests")
    from db.database import init_db
    from sales.db import init_sales_db

    init_db()
    init_sales_db()
    return True


@pytest.fixture
def clean(db):
    from db.database import get_conn

    with get_conn() as conn:
        conn.execute(
            "TRUNCATE sales_thread_messages, sales_threads, sales_email_events, sales_campaign_status, "
            "sales_agent_runs, sales_list_contacts, sales_contacts, sales_companies, sales_lists, "
            "sales_site_visits, sales_directory_cache, seat_daily_usage, email_seats, linkedin_seats, "
            "source_agents, campaign_agents, suppression RESTART IDENTITY CASCADE"
        )
    return True


@pytest.fixture
def llm(monkeypatch):
    """Install canned LLM answers: llm(json_out=fn, research=fn)."""
    def install(**fns):
        for k, v in fns.items():
            monkeypatch.setattr(_llm, k, v)
    return install
