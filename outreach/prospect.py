"""Find ICP-matched companies from the public web (no LinkedIn scraping)."""
from __future__ import annotations

import httpx

from agents.llm import json_out, research
from agents.reporter import report

_SYS = (
    "You are a B2B sales researcher for a solo builder who creates custom AI "
    "agents and automation systems for businesses. You build lists of real "
    "companies led by an active, reachable CEO/founder, using public web "
    "sources. Every company must be real, currently operating, with a working "
    "website. Prioritise recent signals over generic fit - a company that just "
    "raised funding, is visibly scaling, posted about a hiring/ops crunch, or "
    "is still running everything manually is a far better lead than one that "
    "merely matches the industry description."
)

_SCHEMA = {
    "type": "object",
    "properties": {
        "companies": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "company": {"type": "string"},
                    "domain": {"type": "string", "description": "bare domain, e.g. acme.com"},
                    "industry": {"type": "string"},
                    "icp_fit": {"type": "integer", "description": "0-100 fit"},
                    "trigger": {
                        "type": "string",
                        "description": "one concrete why-now reason to reach out",
                    },
                },
                "required": ["company", "domain", "industry", "icp_fit", "trigger"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["companies"],
    "additionalProperties": False,
}


def _domain_is_real(domain: str) -> bool:
    """A cheap but critical trust check: the LLM can and does invent
    plausible-sounding companies/domains even when given real search
    results - never let a fabricated company reach a sales pipeline."""
    for scheme in ("https://", "http://"):
        try:
            r = httpx.head(
                f"{scheme}{domain}", timeout=8, follow_redirects=True,
            )
            if r.status_code < 500:
                return True
        except Exception:  # noqa: BLE001 - try the next scheme
            continue
    return False


def find_leads(icp: str, n: int = 10, exclude: set[str] | None = None) -> list[dict]:
    exclude = exclude or set()
    # Extra headroom - the domain-reality check below drops a meaningful
    # fraction of what the model returns, since it invents plausible-sounding
    # companies even when grounded in real search results.
    ask_n = n + 10
    notes = research(
        _SYS,
        f"Using web search, find real, currently-operating companies matching "
        f"this profile: {icp}\n\n"
        f"Search for and report on {ask_n} SPECIFIC, NAMED real companies (not a "
        f"generic listicle page) - recently-funded startups, companies in news "
        f"articles about scaling/hiring, or similar concrete sources. For each "
        f"one you find in the actual search results, note: name, bare website "
        f"domain, industry, a 0-100 fit score, and ONE concrete, RECENT why-now "
        f"trigger for needing custom AI agents/automation (e.g. just raised "
        f"funding, scaling fast and understaffed on ops, founder posted about "
        f"manual/repetitive work, hiring for roles AI agents could replace). Do "
        f"not invent companies that aren't in the search results.",
        max_tokens=6000,
    )
    data = json_out(
        _SYS,
        "Extract ONLY companies that are explicitly named in the notes below - "
        "do not invent or infer any company not literally mentioned there. Drop "
        "anything without a real domain.\n\n" + notes,
        _SCHEMA,
        max_tokens=6000,
    )
    out: list[dict] = []
    dropped = 0
    for c in data["companies"]:
        dom = c["domain"].lower().strip().replace("https://", "").replace("http://", "")
        dom = dom.replace("www.", "").strip("/")
        if not dom or dom in exclude or dom in {o["domain"] for o in out}:
            continue
        if not _domain_is_real(dom):
            dropped += 1
            continue
        out.append({**c, "domain": dom})
        if len(out) >= n:
            break
    if dropped:
        report(f"  dropped {dropped} unverifiable/fabricated companies", kind="status")
    return out[:n]
