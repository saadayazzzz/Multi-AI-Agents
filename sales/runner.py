"""Run a source agent once: signals -> filter -> score -> import -> log.

One run walks the agent's enabled signal variables least-recently-used
first (Gojiberry's own rotation - see `last_usage` on their variables).
With lead_waterfall on, it keeps going to the next variable until the
run's lead target is reached; with it off, one variable per run. Every
variable attempt writes one sales_agent_runs row with honest counts
(found / duplicates / filtered / below score / imported), which is what
get_agent_logs returns.
"""
from __future__ import annotations

import contextlib
from datetime import datetime, timezone
from typing import Any, Iterator

import psycopg

from agents.reporter import report
from config import settings
from db.database import get_conn
from sales import linkedin as li
from sales.agents import get_agent
from sales.db import jsonb
from sales.lists import add_contacts_to_list, contact_exists, upsert_company, upsert_contact
from sales.scoring import passes, score_candidates
from sales.signals import REGISTRY, SignalUnavailable, people_at_company


@contextlib.contextmanager
def _agent_lock(agent_id: int) -> Iterator[bool]:
    """Session-level advisory lock so the scheduler and a manual "run now"
    can never run the same agent twice at once."""
    conn = psycopg.connect(settings.database_url, autocommit=True)
    try:
        got = conn.execute("SELECT pg_try_advisory_lock(%s, %s)", (7101, agent_id)).fetchone()[0]
        yield got
        if got:
            conn.execute("SELECT pg_advisory_unlock(%s, %s)", (7101, agent_id))
    finally:
        conn.close()


def _strength(n: int) -> str:
    return "high" if n >= 5 else "medium" if n >= 1 else "low"


def _text(c: dict) -> str:
    return " ".join(str(c.get(k) or "") for k in ("full_name", "headline", "job_title", "company", "intent")).lower()


def filter_candidates(agent: dict, cands: list[dict]) -> tuple[list[dict], dict[str, int]]:
    """Workspace dedupe + the agent's hard filters (before spending LLM
    calls on scoring)."""
    stats = {"duplicates": 0, "filtered": 0}
    ignored = [x.lower() for x in agent.get("ignored_companies") or [] if x.strip()]
    mandatory = [x.lower() for x in agent.get("mandatory_keywords") or [] if x.strip()]
    seen: set[str] = set()
    out = []
    for c in cands:
        url = c.get("profile_url")
        if not url or url in seen:
            stats["duplicates"] += 1
            continue
        seen.add(url)
        if contact_exists(url):
            stats["duplicates"] += 1
            continue
        text = _text(c)
        company = (c.get("company") or "").lower()
        if ignored and any(x in company or x in (c.get("headline") or "").lower() for x in ignored):
            stats["filtered"] += 1
            continue
        if mandatory and not any(k in text for k in mandatory):
            stats["filtered"] += 1
            continue
        if c.get("open_to_work") and not agent.get("include_open_to_work_profiles"):
            stats["filtered"] += 1
            continue
        out.append(c)
    return out, stats


def import_leads(agent: dict, cands: list[dict]) -> list[int]:
    ids = []
    for c in cands:
        company_id = None
        if c.get("company"):
            company_id = upsert_company({
                "name": c["company"], "domain": c.get("website"), "linkedin_url": c.get("company_url"),
                "industry": c.get("industry"), "size": c.get("company_size"),
            })
        cid, created = upsert_contact({
            **{k: c.get(k) for k in (
                "full_name", "job_title", "headline", "profile_url", "location", "company",
                "company_url", "website", "industry", "intent_type", "intent", "intent_url",
                "intent_at", "signal_value", "scoring", "total_score", "connection_degree",
            )},
            "company_id": company_id,
            "open_to_work": bool(c.get("open_to_work")),
            "agent_id": agent["id"],
        })
        if created:
            ids.append(cid)
    if agent.get("list_id") and ids:
        add_contacts_to_list(agent["list_id"], ids)
    return ids


def process(agent: dict, cands: list[dict], run_id: int | None = None) -> dict[str, Any]:
    """filter -> score -> threshold -> import. Shared by every agent type."""
    kept, stats = filter_candidates(agent, cands)
    scored = score_candidates(agent, kept)
    good, below = [], 0
    for c in scored:
        if agent.get("exclude_service_providers") and c.get("service_provider"):
            stats["filtered"] += 1
            continue
        if not passes(agent, c):
            below += 1
            continue
        good.append(c)
    room = max(0, int(agent.get("leads_per_run") or 25))
    ids = import_leads(agent, good[:room] if room else good)
    return {"found": len(cands), **stats, "below_score": below, "imported": len(ids), "contact_ids": ids}


def _start_run(agent_id: int, vtype: str, value: str | None) -> int:
    with get_conn() as conn:
        return conn.execute(
            "INSERT INTO sales_agent_runs (agent_id, variable_type, variable_value) VALUES (%s, %s, %s) RETURNING id",
            (agent_id, vtype, value),
        ).fetchone()["id"]


def _finish_run(run_id: int, status: str, res: dict | None = None, error: str | None = None) -> None:
    res = res or {}
    with get_conn() as conn:
        conn.execute(
            """UPDATE sales_agent_runs SET status = %s, found = %s, duplicates = %s, filtered = %s,
                   below_score = %s, imported = %s, error = %s, details = %s, finished_at = now()
               WHERE id = %s""",
            (status, res.get("found", 0), res.get("duplicates", 0), res.get("filtered", 0),
             res.get("below_score", 0), res.get("imported", 0), error,
             jsonb({"contact_ids": res.get("contact_ids", [])}), run_id),
        )


def _seat_for(var: dict) -> dict | None:
    return li.get_seat(var.get("linkedin_seat_id")) or li.default_seat()


def run_agent(agent_id: int, *, force: bool = False, only_type: str | None = None,
              max_variables: int | None = None) -> dict[str, Any]:
    agent = get_agent(agent_id)
    if not agent:
        raise ValueError(f"no source agent {agent_id}")
    if agent["paused"] and not force:
        return {"agent_id": agent_id, "skipped": "paused"}
    with _agent_lock(agent_id) as got:
        if not got:
            return {"agent_id": agent_id, "skipped": "already running"}
        if agent["agent_type"] == "lookalike":
            result = _run_lookalike(agent)
        elif agent["agent_type"] == "website-visitor":
            result = _run_website_visitor(agent)
        else:
            result = _run_autopilot(agent, only_type, max_variables)
        with get_conn() as conn:
            conn.execute("UPDATE source_agents SET last_run = now() WHERE id = %s", (agent_id,))
    return {"agent_id": agent_id, **result}


def _run_autopilot(agent: dict, only_type: str | None, max_variables: int | None) -> dict[str, Any]:
    variables = list(agent.get("variables") or [])
    order = sorted(
        (i for i, v in enumerate(variables) if v.get("enabled", True) and (not only_type or v["type"] == only_type)),
        key=lambda i: variables[i].get("last_usage") or "",
    )
    if not agent.get("lead_waterfall") and max_variables is None:
        max_variables = 1
    target = int(agent.get("leads_per_run") or 25)
    total, runs = 0, []
    for n, i in enumerate(order):
        if max_variables is not None and n >= max_variables:
            break
        if agent.get("lead_waterfall") and total >= target:
            break
        var = variables[i]
        run_id = _start_run(agent["id"], var["type"], var.get("value"))
        try:
            cands = REGISTRY[var["type"]](agent, var, _seat_for(var), target)
            res = process({**agent, "leads_per_run": max(0, target - total)}, cands, run_id)
            _finish_run(run_id, "success", res)
            total += res["imported"]
            var["nb_results_last_launch"] = res["imported"]
            var["strength"] = _strength(res["imported"])
            report(f"  agent {agent['id']} {var['type']} '{var.get('value')}': "
                   f"{res['found']} found, {res['imported']} imported", kind="status")
            runs.append({"type": var["type"], "value": var.get("value"), **{k: v for k, v in res.items() if k != "contact_ids"}})
        except SignalUnavailable as e:
            _finish_run(run_id, "skipped", error=str(e))
            runs.append({"type": var["type"], "value": var.get("value"), "skipped": str(e)})
        except Exception as e:  # noqa: BLE001 - one broken signal must not sink the run
            _finish_run(run_id, "failed", error=f"{type(e).__name__}: {e}"[:1000])
            runs.append({"type": var["type"], "value": var.get("value"), "error": str(e)[:300]})
        var["last_usage"] = datetime.now(timezone.utc).isoformat()
        with get_conn() as conn:
            conn.execute("UPDATE source_agents SET variables = %s WHERE id = %s", (jsonb(variables), agent["id"]))
    if not order:
        return {"imported": 0, "runs": [], "note": "no enabled signal variables"}
    return {"imported": total, "runs": runs}


# ------------------------------------------------------------- lookalike --

_LOOKALIKE_SCHEMA = {
    "type": "object",
    "properties": {"queries": {"type": "array", "items": {"type": "string"}}},
    "required": ["queries"],
    "additionalProperties": False,
}


def _run_lookalike(agent: dict) -> dict[str, Any]:
    """Find people like the best leads you already have: seeds are the
    profile URLs in additional_criteria, else the list's top-scored contacts."""
    from agents.llm import json_out

    run_id = _start_run(agent["id"], "LOOKALIKE", None)
    try:
        seat = li.default_seat()
        if not li.has_session(seat):
            raise SignalUnavailable("lookalike agents need a logged-in LinkedIn seat")
        seeds = [u for u in (agent.get("additional_criteria") or "").split() if "linkedin.com/in/" in u]
        profiles = [li.call("profile", {"url": u}, seat) for u in seeds[:5]]
        if not profiles:
            with get_conn() as conn:
                profiles = conn.execute(
                    "SELECT c.full_name, c.headline, c.job_title, c.company, c.industry, c.location "
                    "FROM sales_contacts c JOIN sales_list_contacts lc ON lc.contact_id = c.id "
                    "WHERE lc.list_id = %s ORDER BY c.total_score DESC NULLS LAST LIMIT 10",
                    (agent["list_id"],),
                ).fetchall()
        if not profiles:
            raise SignalUnavailable("no seed profiles - add LinkedIn URLs to additional_criteria")
        q = json_out(
            "You turn example customers into LinkedIn people-search keyword queries that find "
            "similar people (same kind of role, company and market). 3-5 short queries.",
            "\n".join(f"- {p.get('headline') or p.get('job_title')} at {p.get('company')} ({p.get('location')})"
                      for p in profiles),
            _LOOKALIKE_SCHEMA, max_tokens=500,
        )
        cands = []
        for query in q["queries"][:5]:
            for p in li.call("search_people", {"query": query, "max": 10}, seat) or []:
                from sales.signals import _cand
                c = _cand(p, "LOOKALIKE", query, intent=f"Looks like your best leads (search: {query})")
                if c:
                    cands.append(c)
        res = process(agent, cands, run_id)
        _finish_run(run_id, "success", res)
        return {"imported": res["imported"], "runs": [{"type": "LOOKALIKE", **{k: v for k, v in res.items() if k != 'contact_ids'}}]}
    except SignalUnavailable as e:
        _finish_run(run_id, "skipped", error=str(e))
        return {"imported": 0, "skipped": str(e)}
    except Exception as e:  # noqa: BLE001
        _finish_run(run_id, "failed", error=str(e)[:1000])
        return {"imported": 0, "error": str(e)}


# -------------------------------------------------------- website visitor --

def _run_website_visitor(agent: dict) -> dict[str, Any]:
    """Companies identified from site visits (reverse IP, see sales/tracking.py)
    -> decision-makers at each. One credit = one company processed, capped by
    max_credit_usage per month like Gojiberry."""
    run_id = _start_run(agent["id"], "WEBSITE_VISIT", None)
    try:
        with get_conn() as conn:
            if agent.get("max_credit_usage") is not None:
                used = conn.execute(
                    "SELECT COUNT(DISTINCT org_domain) n FROM sales_site_visits WHERE agent_id = %s "
                    "AND processed AND org_domain IS NOT NULL AND ts >= date_trunc('month', now())",
                    (agent["id"],),
                ).fetchone()["n"]
                budget = max(0, agent["max_credit_usage"] - used)
            else:
                budget = 20
            visits = conn.execute(
                "SELECT org, org_domain, MAX(page_url) page_url, COUNT(*) n FROM sales_site_visits "
                "WHERE agent_id = %s AND NOT processed AND org_domain IS NOT NULL "
                "GROUP BY org, org_domain ORDER BY n DESC LIMIT %s",
                (agent["id"], budget),
            ).fetchall()
            conn.execute("UPDATE sales_site_visits SET processed = true WHERE agent_id = %s AND NOT processed AND org_domain IS NULL",
                         (agent["id"],))
        seat = li.default_seat()
        cands = []
        from sales.signals import _cand
        for v in visits:
            for p in people_at_company(v["org"] or v["org_domain"], agent.get("target_job_titles") or [], seat):
                c = _cand({**p, "company": v["org"]}, "WEBSITE_VISIT", v["org"],
                          intent=f"Someone from {v['org']} visited {v['page_url']} ({v['n']} views)")
                if c:
                    cands.append(c)
            with get_conn() as conn:
                conn.execute("UPDATE sales_site_visits SET processed = true WHERE agent_id = %s AND org_domain = %s",
                             (agent["id"], v["org_domain"]))
        with get_conn() as conn:
            conn.execute("UPDATE source_agents SET current_credit_usage = current_credit_usage + %s WHERE id = %s",
                         (len(visits), agent["id"]))
        res = process(agent, cands, run_id)
        _finish_run(run_id, "success", res)
        return {"imported": res["imported"], "companies": len(visits)}
    except Exception as e:  # noqa: BLE001
        _finish_run(run_id, "failed", error=str(e)[:1000])
        return {"imported": 0, "error": str(e)}


def due_agents() -> list[int]:
    with get_conn() as conn:
        return [r["id"] for r in conn.execute(
            """SELECT id FROM source_agents
               WHERE NOT paused AND list_id IS NOT NULL
                 AND (last_run IS NULL OR last_run < now() - make_interval(mins => run_interval_minutes))
               ORDER BY last_run NULLS FIRST"""
        ).fetchall()]
