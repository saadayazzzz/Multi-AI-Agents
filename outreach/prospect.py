"""Find ICP-matched companies from the public web (no LinkedIn scraping)."""
from __future__ import annotations

from agents.llm import json_out, research

_SYS = (
    "You are a B2B sales researcher. You build lists of real companies that match "
    "an ideal-customer profile, using public web sources. Every company must be a "
    "real, currently-operating business with a working website."
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


def find_leads(icp: str, n: int = 10, exclude: set[str] | None = None) -> list[dict]:
    exclude = exclude or set()
    notes = research(
        _SYS,
        f"Ideal customer profile:\n{icp}\n\n"
        f"Using web search, find about {n + 6} real companies that fit. For each: "
        f"name, bare website domain, industry, a 0-100 fit score, and ONE concrete "
        f"why-now trigger to contact them about their visibility in AI search "
        f"(e.g. recently raised funding, hiring an SEO/growth lead, launched a new "
        f"product, competitor getting more AI-answer coverage).",
        max_tokens=6000,
    )
    data = json_out(
        _SYS,
        "Turn this into structured records. Drop anything without a real domain.\n\n" + notes,
        _SCHEMA,
        max_tokens=6000,
    )
    out: list[dict] = []
    for c in data["companies"]:
        dom = c["domain"].lower().strip().replace("https://", "").replace("http://", "")
        dom = dom.replace("www.", "").strip("/")
        if not dom or dom in exclude or dom in {o["domain"] for o in out}:
            continue
        out.append({**c, "domain": dom})
    return out[:n]
