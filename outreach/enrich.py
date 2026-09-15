"""Attach a likely decision-maker + contact email + a per-lead visibility finding."""
from __future__ import annotations

from typing import Any

from agents.llm import json_out, research

_SYS = (
    "You are a B2B sales researcher. From public sources, identify the single best "
    "person to contact at a company about improving the company's visibility in AI "
    "search engines (typically Head/Director of Marketing, Growth, or SEO)."
)

_SCHEMA = {
    "type": "object",
    "properties": {
        "contact_name": {"type": ["string", "null"]},
        "contact_role": {"type": "string"},
        "context": {"type": "string", "description": "one line about the company's current focus"},
        "trigger": {"type": "string", "description": "refined why-now hook"},
    },
    "required": ["contact_name", "contact_role", "context", "trigger"],
    "additionalProperties": False,
}


def guess_email(domain: str, name: str | None) -> tuple[str, str]:
    """Return (email, status). Pattern-guessed unless a real address is known."""
    if not name:
        return f"hello@{domain}", "guessed"
    parts = [p for p in name.lower().replace(".", " ").split() if p.isalpha()]
    if len(parts) >= 2:
        return f"{parts[0]}.{parts[-1]}@{domain}", "guessed"
    if parts:
        return f"{parts[0]}@{domain}", "guessed"
    return f"hello@{domain}", "guessed"


def enrich_lead(lead: dict[str, Any]) -> dict[str, Any]:
    notes = research(
        _SYS,
        f"Company: {lead['company']}  ({lead['domain']})\n"
        f"Industry: {lead.get('industry', '?')}\n\n"
        f"Using web search: who is the best person to contact about the company's "
        f"AI-search visibility? Give their name if you can find one, their role, a "
        f"one-line note on what the company is currently focused on, and a refined "
        f"why-now trigger.",
        max_tokens=3000,
    )
    d = json_out(_SYS, "Structure this.\n\n" + notes, _SCHEMA, max_tokens=1500)
    email, status = guess_email(lead["domain"], d["contact_name"])
    return {
        "contact_name": d["contact_name"],
        "contact_role": d["contact_role"],
        "contact_email": email,
        "email_status": status,
        "trigger": d["trigger"] or lead.get("trigger"),
        "context": d["context"],
    }
