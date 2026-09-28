"""Attach a likely decision-maker + contact email + a per-lead visibility finding."""
from __future__ import annotations

from typing import Any

from agents.llm import json_out, research

_SYS = (
    "You are a B2B sales researcher. From public sources, identify the CEO or "
    "founder of a company - the decision-maker for a custom AI agent/automation "
    "build, since that's a strategic, budget-owning decision at most small-to-"
    "mid companies, not something a department head signs off on alone."
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
    # prospect.py already found a sourced contact (a real LinkedIn post) for
    # most leads now - only spend a research call hunting for one when it didn't.
    if lead.get("contact_name"):
        email, status = guess_email(lead["domain"], lead["contact_name"])
        return {
            "contact_name": lead["contact_name"],
            "contact_role": lead.get("contact_role") or "Founder",
            "contact_email": email,
            "email_status": status,
            "trigger": lead.get("trigger"),
            "context": None,
        }

    notes = research(
        _SYS,
        f"Company: {lead['company']}  ({lead['domain']})\n"
        f"Industry: {lead.get('industry', '?')}\n\n"
        f"Using web search: who is the CEO or founder of this company? Give their "
        f"name if you can find one (contact_role should literally be 'CEO' or "
        f"'Founder' / 'Co-Founder', not a department title), a one-line note on "
        f"what the company is currently focused on, and a refined, RECENT why-now "
        f"trigger for why they'd want custom AI agents/automation right now.",
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
