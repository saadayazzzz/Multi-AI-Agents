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
