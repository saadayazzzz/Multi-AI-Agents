"""Source Agents + Campaign Agents - our own equivalent of Gojiberry's two-
entity model, confirmed via their own MCP API (list_agents/list_campaigns),
not guessed from screenshots:

- A Source Agent finds and scores leads against an ICP (job titles,
  industries, company sizes/types, locations, keywords, exclusions). It
  does NOT do outreach.
- A Campaign Agent runs the multi-step outreach sequence (connect, message,
  email, profile visit, ...) against whoever a source agent found. It's
  linked to exactly one `campaigns` row (our existing table) via
  source_agents.campaign_id - same relationship Gojiberry expresses through
  list membership.

Three of Gojiberry's four signal types are premium/paid even on their own
platform (confirmed from their own agent config: RECENT_FUNDING_EVENT and
RECENTLY_CHANGED_JOB are flagged `"premium": true`) - we don't have those
data sources either, so a source agent here only ever uses SEARCH_KEYWORD
and "top active profiles" (our live LinkedIn-session search, sorted by
Latest), both backed by outreach/prospect.py's real pipeline.
"""
from __future__ import annotations

from typing import Any

from db import get_conn


def create_source_agent(
    name: str,
    job_titles: list[str],
    industries: list[str],
    company_sizes: list[str],
    locations: list[str],
    company_types: list[str],
    keywords: list[str],
    ignored_companies: list[str] | None = None,
    min_lead_score: float = 0.5,
    exclude_service_providers: bool = True,
    include_open_to_work_profiles: bool = False,
    campaign_id: int | None = None,
) -> int:
    kw = [{"value": k, "last_usage": None, "nb_results_last_launch": None} for k in keywords]
    with get_conn() as conn:
        return conn.execute(
            """
            INSERT INTO source_agents (
                name, target_job_titles, target_industries, target_company_sizes,
                target_locations, target_company_types, keywords, ignored_companies,
                min_lead_score, exclude_service_providers, include_open_to_work_profiles,
                campaign_id
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
            """,
            (
                name, job_titles, industries, company_sizes, locations, company_types,
                __import__("json").dumps(kw), ignored_companies or [],
                min_lead_score, exclude_service_providers, include_open_to_work_profiles,
                campaign_id,
            ),
        ).fetchone()["id"]


def create_campaign_agent(
    campaign_id: int,
    steps: list[dict] | None = None,
    tone: str = "professional",
    goal: str = "warm",
    launch_hour: int = 9,
) -> int:
    import json as _json

    default_steps = steps or [
        {"type": "invitation", "step_number": 0, "like_posts_before_invitation": True, "delay_after_last_step": 2},
        {"type": "message", "step_number": 1, "message_mode": "ai", "message": "", "delay_after_last_step": 3},
        {"type": "email", "step_number": 2, "message_mode": "ai", "message": "", "subject": "", "delay_after_last_step": 2},
    ]
    with get_conn() as conn:
        return conn.execute(
            """
            INSERT INTO campaign_agents (campaign_id, steps, tone, goal, launch_hour)
            VALUES (%s, %s, %s, %s, %s)
            RETURNING id
            """,
            (campaign_id, _json.dumps(default_steps), tone, goal, launch_hour),
        ).fetchone()["id"]


def list_source_agents() -> list[dict]:
    with get_conn() as conn:
        return conn.execute("SELECT * FROM source_agents ORDER BY id DESC").fetchall()


def list_campaign_agents() -> list[dict]:
    with get_conn() as conn:
        return conn.execute("SELECT * FROM campaign_agents ORDER BY id DESC").fetchall()


def get_source_agent(agent_id: int) -> dict | None:
    with get_conn() as conn:
        return conn.execute("SELECT * FROM source_agents WHERE id = %s", (agent_id,)).fetchone()


def _icp_prompt_for_agent(agent: dict) -> str:
    parts = []
    if agent["target_job_titles"]:
        parts.append(f"Decision-makers: {', '.join(agent['target_job_titles'])}")
    if agent["target_industries"]:
        parts.append(f"Industries: {', '.join(agent['target_industries'])}")
    if agent["target_company_sizes"]:
        parts.append(f"Company size: {', '.join(agent['target_company_sizes'])}")
    if agent["target_locations"]:
        parts.append(f"Locations: {', '.join(agent['target_locations'])}")
    if agent["target_company_types"]:
        parts.append(f"Company type: {', '.join(agent['target_company_types'])}")
    kws = [k["value"] for k in (agent.get("keywords") or [])]
    if kws:
        parts.append(f"Keywords to match: {', '.join(kws)}")
    excl = list(agent.get("ignored_companies") or [])
    if agent.get("exclude_service_providers"):
        excl.append("agencies, consultants, freelancers, and other service providers")
    if excl:
        parts.append(f"Exclude: {', '.join(excl)}")
    return ". ".join(parts)


def run_and_process_source_agent(agent_id: int, n: int = 5) -> dict:
    """The continuous-background-scan loop Gojiberry's `leadWaterfall` +
    `agentType: autopilot` actually is: one pass of find -> insert -> enrich
    -> draft -> Notion-sync against a source agent's linked campaign. Meant
    to be called on a recurring schedule (see JARVIS's schedule_recurring)
    so leads accumulate across many short runs instead of needing one
    single search to succeed - the real reason their hit rate looks higher
    than a single on-demand search: continuous volume, not looser rules."""
    from db import get_conn
    from outreach.excel import export_xlsx
    from outreach.pipeline import _campaign, _draft, _enrich, _for_status, _sync_notion

    agent = get_source_agent(agent_id)
    if not agent:
        raise ValueError(f"no source agent {agent_id}")
    if not agent["campaign_id"]:
        raise ValueError(f"source agent {agent_id} has no linked campaign - link one first")

    found = run_source_agent(agent_id, n=n)
    cid = agent["campaign_id"]
    camp = _campaign(cid)
    with get_conn() as conn:
        for c in found:
            conn.execute(
                """
                INSERT INTO leads (campaign_id, company, domain, industry, icp_fit, trigger,
                    contact_name, contact_role, linkedin_url, linkedin_activity)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (campaign_id, domain) DO NOTHING
                """,
                (cid, c["company"], c["domain"], c.get("industry"), c.get("icp_fit"),
                 c.get("trigger"), c.get("contact_name"), c.get("contact_role"),
                 c.get("linkedin_url"), c.get("posted_when")),
            )
    _for_status(cid, "new", lambda lead: _enrich(lead))
    with get_conn() as conn:
        conn.execute("UPDATE leads SET status='scored' WHERE campaign_id=%s AND status='enriched'", (cid,))
    _for_status(cid, "scored", lambda lead: _draft(lead, camp))
    synced = _sync_notion(cid)
    path = export_xlsx(cid, "leads.xlsx")
    return {"found": len(found), "synced": synced, "xlsx": str(path)}


def run_source_agent(agent_id: int, n: int = 5) -> list[dict]:
    """Prospect against a source agent's ICP, using its min_lead_score as
    the real filter threshold (converted to our 0-100 icp_fit scale),
    and record real run telemetry on its keywords - same
    last_usage/nb_results_last_launch fields Gojiberry's own agents carry,
    kept honest rather than faked."""
    import json as _json
    from datetime import datetime, timezone

    import outreach.prospect as prospect

    agent = get_source_agent(agent_id)
    if not agent:
        raise ValueError(f"no source agent {agent_id}")

    icp_prompt = _icp_prompt_for_agent(agent)
    old_min = prospect.MIN_ICP_FIT
    prospect.MIN_ICP_FIT = round(float(agent["min_lead_score"]) * 100)
    try:
        with get_conn() as conn:
            have = set()
            if agent["campaign_id"]:
                have = {
                    r["domain"]
                    for r in conn.execute(
                        "SELECT domain FROM leads WHERE campaign_id = %s", (agent["campaign_id"],)
                    ).fetchall()
                }
        # Two signals, same as Gojiberry's own agent (confirmed via their
        # get_agent_logs): a narrow keyword/pain-point search (low yield,
        # 0-1 per run, same as theirs) and a broad "active profile" search
        # that isn't gated on post content at all (their big-volume signal
        # - 189 leads in one of their own runs). Combine + dedupe by domain.
        kw_leads = prospect.find_leads(icp_prompt, n=n, exclude=have)
        have2 = have | {c["domain"] for c in kw_leads}
        active_leads = prospect.find_active_profiles(
            agent["target_job_titles"], icp_prompt, n=n, exclude=have2,
        )
        leads = kw_leads + active_leads
    finally:
        prospect.MIN_ICP_FIT = old_min

    now = datetime.now(timezone.utc).isoformat()
    kws = agent.get("keywords") or []
    for k in kws:
        k["last_usage"] = now
        k["nb_results_last_launch"] = len(kw_leads)
    with get_conn() as conn:
        conn.execute(
            "UPDATE source_agents SET last_run = now(), keywords = %s WHERE id = %s",
            (_json.dumps(kws), agent_id),
        )
    return leads


if __name__ == "__main__":
    # Standalone continuous runner - deliberately separate from JARVIS's
    # own task queue/orchestrator (kept out per request). Mirrors what
    # Gojiberry's `agentType: autopilot` actually is: a loop that keeps
    # re-scanning on an interval so leads accumulate over many short runs.
    #   python -m outreach.agents <source_agent_id> [interval_minutes]
    import sys
    import time

    agent_id = int(sys.argv[1])
    interval_min = int(sys.argv[2]) if len(sys.argv) > 2 else 60

    print(f"agents: autopilot loop for source agent {agent_id}, every {interval_min}m")
    while True:
        try:
            result = run_and_process_source_agent(agent_id)
            print(f"agents: run complete - {result}")
        except Exception as e:  # noqa: BLE001 - one bad run shouldn't kill the loop
            print(f"agents: run failed - {e}")
        time.sleep(interval_min * 60)
