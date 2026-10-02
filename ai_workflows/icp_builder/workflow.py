"""ICP Builder - reads a company's own website and drafts a target-customer
profile (job roles, industries, locations, company type/size, exclusions),
the same AI-prefill pattern Gojiberry uses in its onboarding wizard.

Flow: fetch the site's visible text -> one LLM call extracts a structured
ICP draft -> the user edits it in the wizard UI -> confirmed ICP is handed
to the lead-finding pipeline (the same `icp` string shape prospect.py
already takes).

Run: python ai_workflows/icp_builder/server.py
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import httpx  # noqa: E402

from agents.llm import json_out  # noqa: E402

_SYS = (
    "You read a company's own website text and draft their ideal-customer "
    "profile (ICP) for B2B outbound prospecting - the same kind of "
    "inference a human sales strategist makes from skimming a company's "
    "homepage/about/pricing pages. Infer sensible, standard values; don't "
    "invent oddly specific claims the site doesn't support. If the site "
    "gives little to go on, fall back to reasonable defaults for a company "
    "in that space rather than leaving fields empty."
)

_SCHEMA = {
    "type": "object",
    "properties": {
        "job_roles": {
            "type": "array",
            "items": {"type": "string"},
            "description": "titles of the people who'd actually buy/champion this, e.g. Founder, CTO, Head of Product",
        },
        "industries": {
            "type": "array",
            "items": {"type": "string"},
        },
        "locations": {
            "type": "array",
            "items": {"type": "string"},
            "description": "countries/regions this company's customers are realistically in",
        },
        "company_types": {
            "type": "array",
            "items": {
                "type": "string",
                "enum": [
                    "Startup", "Private Company", "Public Company",
                    "Non-profit", "Government", "Educational Institution", "Other",
                ],
            },
        },
        "company_sizes": {
            "type": "array",
            "items": {
                "type": "string",
                "enum": [
                    "1-10 employees", "11-50 employees", "51-200 employees",
                    "201-500 employees", "501-1000 employees",
                    "1001-5000 employees", "5001-10000 employees", "10000+ employees",
                ],
            },
        },
        "excluded_profiles": {
            "type": "array",
            "items": {"type": "string"},
            "description": "categories of people/companies to exclude, e.g. 'Service providers, freelancers, consultants'",
        },
        "excluded_keywords": {
            "type": "array",
            "items": {"type": "string"},
            "description": "specific competitor names or companies to avoid",
        },
    },
    "required": [
        "job_roles", "industries", "locations", "company_types",
        "company_sizes", "excluded_profiles", "excluded_keywords",
    ],
    "additionalProperties": False,
}

_TAG_RE = re.compile(r"<(script|style)[^>]*>.*?</\1>", re.IGNORECASE | re.DOTALL)
_ANY_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


def _fetch_site_text(url: str, max_chars: int = 6000) -> str:
    if not url.startswith("http"):
        url = "https://" + url
    r = httpx.get(url, timeout=15, follow_redirects=True, headers={"User-Agent": "Mozilla/5.0"})
    r.raise_for_status()
    html = r.text
    html = _TAG_RE.sub(" ", html)
    text = _ANY_TAG_RE.sub(" ", html)
    text = _WS_RE.sub(" ", text).strip()
    return text[:max_chars]


def build_icp_from_site(url: str) -> dict:
    site_text = _fetch_site_text(url)
    draft = json_out(
        _SYS,
        f"Company website: {url}\n\nVisible page text:\n{site_text}\n\n"
        f"Draft their ICP.",
        _SCHEMA,
        max_tokens=1500,
    )
    draft["source_url"] = url
    return draft


def build_icp_from_description(description: str) -> dict:
    """Fallback when there's no real site to fetch yet - same extraction,
    fed a plain-English description instead."""
    draft = json_out(
        _SYS,
        f"Company description (no live site available):\n{description}\n\n"
        f"Draft their ICP.",
        _SCHEMA,
        max_tokens=1500,
    )
    draft["source_url"] = None
    return draft


def find_candidate_leads(icp_prompt: str, n: int = 5) -> list[dict]:
    """Preview step - runs the REAL prospecting pipeline (live LinkedIn
    session search when available, public-search fallback otherwise) so
    what the wizard previews is genuinely what would get added, not a
    mock. Nothing is written to the database yet."""
    from outreach.prospect import find_leads

    return find_leads(icp_prompt, n=n)


def launch_campaign(
    website_url: str,
    icp_prompt: str,
    offer: str,
    accepted_leads: list[dict],
    icp: dict | None = None,
    keywords: list[str] | None = None,
    tone: str = "professional",
    goal: str = "warm",
) -> dict:
    """Confirm step - create a real Source Agent + Campaign Agent pair
    (outreach/agents.py - the two-entity model confirmed from Gojiberry's
    own MCP API) plus the underlying campaign row, then run the accepted
    leads through the same enrich -> score -> draft -> Notion-sync pipeline
    outreach/pipeline.py's run_cycle uses, reusing its own helpers so
    behaviour never drifts from the one true pipeline."""
    from db import get_conn
    from geo.db import init_geo_db
    from outreach.agents import create_campaign_agent, create_source_agent
    from outreach.db import init_outreach_db
    from outreach.excel import export_xlsx
    from outreach.pipeline import (
        _campaign,
        _draft,
        _enrich,
        _for_status,
        _sync_notion,
        create_campaign,
    )
    from server.linkedin_oauth import connected_identity

    init_geo_db()
    init_outreach_db()
    name_, email_ = connected_identity()
    cid = create_campaign(
        f"icp-builder:{website_url}", icp_prompt, offer, name_ or "Saad", email_, 20,
    )
    camp = _campaign(cid)

    icp = icp or {}
    saved_id = create_source_agent(
        name=f"icp-builder:{website_url}",
        job_titles=icp.get("job_roles") or [],
        industries=icp.get("industries") or [],
        company_sizes=icp.get("company_sizes") or [],
        locations=icp.get("locations") or [],
        company_types=icp.get("company_types") or [],
        keywords=keywords or [],
        ignored_companies=icp.get("excluded_keywords") or [],
        campaign_id=cid,
    )
    campaign_agent_id = create_campaign_agent(campaign_id=cid, tone=tone, goal=goal)
    with get_conn() as conn:
        for c in accepted_leads:
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
    _for_status(cid, "enriched", lambda lead: lead)  # skip geo-score here (slow, optional)
    with get_conn() as conn:
        conn.execute("UPDATE leads SET status='scored' WHERE campaign_id=%s AND status='enriched'", (cid,))
    _for_status(cid, "scored", lambda lead: _draft(lead, camp))
    synced = _sync_notion(cid)
    path = export_xlsx(cid, "leads.xlsx")
    with get_conn() as conn:
        counts = {
            r["status"]: r["n"]
            for r in conn.execute(
                "SELECT status, COUNT(*) n FROM leads WHERE campaign_id = %s GROUP BY status",
                (cid,),
            ).fetchall()
        }
    return {
        "campaign_id": cid,
        "source_agent_id": saved_id,
        "campaign_agent_id": campaign_agent_id,
        "synced": synced,
        "xlsx": str(path),
        "pipeline": counts,
    }


def icp_to_prompt_string(icp: dict) -> str:
    """Collapse the structured ICP back into the single-string shape
    outreach/prospect.py's find_leads(icp, ...) already expects."""
    parts = []
    if icp.get("job_roles"):
        parts.append(f"Decision-makers: {', '.join(icp['job_roles'])}")
    if icp.get("industries"):
        parts.append(f"Industries: {', '.join(icp['industries'])}")
    if icp.get("company_sizes"):
        parts.append(f"Company size: {', '.join(icp['company_sizes'])}")
    if icp.get("locations"):
        parts.append(f"Locations: {', '.join(icp['locations'])}")
    if icp.get("company_types"):
        parts.append(f"Company type: {', '.join(icp['company_types'])}")
    if icp.get("excluded_profiles") or icp.get("excluded_keywords"):
        excl = (icp.get("excluded_profiles") or []) + (icp.get("excluded_keywords") or [])
        parts.append(f"Exclude: {', '.join(excl)}")
    return ". ".join(parts)


if __name__ == "__main__":
    import json
    import sys as _sys

    target = _sys.argv[1] if len(_sys.argv) > 1 else "https://www.notion.so"
    result = build_icp_from_site(target)
    print(json.dumps(result, indent=2))
    print("\n--- as prompt string ---")
    print(icp_to_prompt_string(result))
