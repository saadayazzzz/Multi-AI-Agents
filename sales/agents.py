"""Source agents: CRUD + validation, mirroring Gojiberry's create_agent rules."""
from __future__ import annotations

import secrets
from typing import Any

from db.database import get_conn
from sales.constants import (
    AGENT_TYPES, COMPANY_SIZES, COMPANY_TYPES, FLAG_SIGNALS, FORBIDDEN_SIGNALS, SIGNALS,
    normalize_company_size,
)
from sales.db import jsonb


class AgentError(ValueError):
    pass


def validate_variables(variables: list[dict], agent_type: str = "autopilot") -> list[dict]:
    """Same rules Gojiberry's API enforces: 4-15 variables for autopilot,
    each with a type and a value, no LOOKALIKE / JOB_SEARCH."""
    if agent_type != "autopilot":
        if variables:
            raise AgentError("signal variables are only used by autopilot agents")
        return []
    if not variables:
        return []
    if not 4 <= len(variables) <= 15:
        raise AgentError(f"autopilot agents need 4-15 signal variables, got {len(variables)}")
    out = []
    for v in variables:
        t = (v.get("type") or "").strip()
        if t in FORBIDDEN_SIGNALS:
            raise AgentError(f"{t} variables are not allowed")
        if t not in SIGNALS:
            raise AgentError(f"unknown signal type {t!r}")
        value = str(v.get("value") or "").strip()
        if not value:
            raise AgentError(f"{t} variable needs a value")
        if t in FLAG_SIGNALS and value.lower() not in {"true", "1", "yes"}:
            value = "true" if value.lower() not in {"false", "0", "no"} else "false"
        if t in {"COMPETITOR_PAGE_URL", "INFLUENCER_PAGE_URL", "YOUR_COMPANY", "YOUR_COMPANY_FOLLOWERS"} \
                and "linkedin.com/" not in value:
            raise AgentError(f"{t} value must be a LinkedIn page URL")
        out.append({
            "type": t,
            "value": value,
            "enabled": v.get("enabled", True) and value != "false",
            "options": v.get("options") or {},
            "linkedin_seat_id": v.get("linkedin_seat_id") or v.get("linkedinSeatId"),
            "strength": v.get("strength"),
            "last_usage": v.get("last_usage"),
            "nb_results_last_launch": v.get("nb_results_last_launch"),
        })
    return out


def _sizes(sizes: list[str]) -> list[str]:
    out = []
    for s in sizes or []:
        n = normalize_company_size(s)
        if not n:
            raise AgentError(f"unknown company size {s!r} (use one of {COMPANY_SIZES})")
        out.append(n)
    return list(dict.fromkeys(out))


def _types(types: list[str]) -> list[str]:
    for t in types or []:
        if t not in COMPANY_TYPES:
            raise AgentError(f"unknown company type {t!r} (use one of {COMPANY_TYPES})")
    return list(types or [])


def create_agent(
    *, name: str, list_id: int, target_job_titles: list[str], target_industries: list[str],
    target_company_sizes: list[str], target_locations: list[str], target_company_types: list[str],
    agent_type: str = "autopilot", variables: list[dict] | None = None,
    ignored_companies: list[str] | None = None, mandatory_keywords: list[str] | None = None,
    min_lead_score: float = 0.6, exclude_service_providers: bool = True,
    include_open_to_work_profiles: bool = False, skip_icp_filter: bool = False,
    lead_waterfall: bool = True, additional_criteria: str = "", paused: bool = False,
    max_credit_usage: int | None = None, run_interval_minutes: int = 240, leads_per_run: int = 25,
) -> dict:
    if agent_type not in AGENT_TYPES:
        raise AgentError(f"agent_type must be one of {AGENT_TYPES}")
    if not 0 <= float(min_lead_score) <= 1:
        raise AgentError("min_lead_score is 0-1")
    with get_conn() as conn:
        if not conn.execute("SELECT 1 FROM sales_lists WHERE id = %s", (list_id,)).fetchone():
            raise AgentError(f"list {list_id} not found - create the list first")
    vars_ = validate_variables(variables or [], agent_type)
    with get_conn() as conn:
        row = conn.execute(
            """
            INSERT INTO source_agents (
                name, list_id, agent_type, variables, target_job_titles, target_industries,
                target_company_sizes, target_locations, target_company_types, ignored_companies,
                mandatory_keywords, min_lead_score, exclude_service_providers,
                include_open_to_work_profiles, skip_icp_filter, lead_waterfall,
                additional_criteria, paused, max_credit_usage, run_interval_minutes, leads_per_run
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
            """,
            (
                name, list_id, agent_type, jsonb(vars_), target_job_titles, target_industries,
                _sizes(target_company_sizes), target_locations, _types(target_company_types),
                ignored_companies or [], mandatory_keywords or [], min_lead_score,
                exclude_service_providers, include_open_to_work_profiles, skip_icp_filter,
                lead_waterfall, additional_criteria or "", paused, max_credit_usage,
                run_interval_minutes, leads_per_run,
            ),
        ).fetchone()
    return get_agent(row["id"])


_UPDATABLE = {
    "name", "list_id", "variables", "target_job_titles", "target_industries", "target_company_sizes",
    "target_locations", "target_company_types", "ignored_companies", "mandatory_keywords",
    "min_lead_score", "exclude_service_providers", "include_open_to_work_profiles", "skip_icp_filter",
    "lead_waterfall", "additional_criteria", "paused", "max_credit_usage", "run_interval_minutes",
    "leads_per_run",
}


def update_agent(agent_id: int, fields: dict[str, Any]) -> dict:
    agent = get_agent(agent_id)
    if not agent:
        raise AgentError(f"agent {agent_id} not found")
    sets, vals = [], []
    for k, v in fields.items():
        if k not in _UPDATABLE or v is None:
            continue
        if k == "variables":
            v = jsonb(validate_variables(v, agent["agent_type"]))
        elif k == "target_company_sizes":
            v = _sizes(v)
        elif k == "target_company_types":
            v = _types(v)
        sets.append(f"{k} = %s")
        vals.append(v)
    if sets:
        with get_conn() as conn:
            conn.execute(
                f"UPDATE source_agents SET {', '.join(sets)}, updated_at = now() WHERE id = %s",
                (*vals, agent_id),
            )
    return get_agent(agent_id)


def get_agent(agent_id: int) -> dict | None:
    with get_conn() as conn:
        a = conn.execute(
            "SELECT a.*, l.campaign_agent_id AS list_campaign_id FROM source_agents a "
            "LEFT JOIN sales_lists l ON l.id = a.list_id WHERE a.id = %s",
            (agent_id,),
        ).fetchone()
        if a and a["agent_type"] == "website-visitor":
            a["tracking_script"] = tracking_snippet(a)
    return a


def list_agents() -> list[dict]:
    with get_conn() as conn:
        return conn.execute(
            "SELECT a.*, l.campaign_agent_id AS list_campaign_id, "
            "(SELECT COUNT(*) FROM sales_contacts c WHERE c.agent_id = a.id) AS leads_found "
            "FROM source_agents a LEFT JOIN sales_lists l ON l.id = a.list_id ORDER BY a.id DESC"
        ).fetchall()


def delete_agent(agent_id: int) -> None:
    with get_conn() as conn:
        conn.execute("DELETE FROM source_agents WHERE id = %s", (agent_id,))


def agent_logs(agent_id: int, date_from: str | None = None, date_to: str | None = None, limit: int = 100) -> list[dict]:
    where, vals = ["agent_id = %s"], [agent_id]
    if date_from:
        where.append("started_at >= %s::timestamptz")
        vals.append(date_from)
    if date_to:
        where.append("started_at <= %s::timestamptz")
        vals.append(date_to)
    with get_conn() as conn:
        return conn.execute(
            f"SELECT * FROM sales_agent_runs WHERE {' AND '.join(where)} ORDER BY started_at DESC, id DESC LIMIT %s",
            (*vals, min(limit, 100)),
        ).fetchall()


# ---------------------------------------------------- website-visitor agent --

def tracking_id(agent: dict) -> str:
    """Stable per-agent public id for the website tracking snippet."""
    with get_conn() as conn:
        r = conn.execute("SELECT tracking_script_id FROM source_agents WHERE id = %s", (agent["id"],)).fetchone()
        if r and r["tracking_script_id"]:
            return r["tracking_script_id"]
        tid = secrets.token_urlsafe(12)
        conn.execute("UPDATE source_agents SET tracking_script_id = %s WHERE id = %s", (tid, agent["id"]))
        return tid


def tracking_snippet(agent: dict) -> str:
    from config import settings

    base = settings.public_base_url or f"http://{settings.server_host}:{settings.server_port}"
    tid = tracking_id(agent)
    return (
        f'<script async src="{base}/api/sales/track/{tid}.js"></script>'
    )
