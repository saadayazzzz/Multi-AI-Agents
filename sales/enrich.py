"""Contact enrichment: work email (+ phone when a provider is configured).

Email waterfall:
  1. Hunter.io email-finder, if HUNTER_API_KEY is set (verified when its
     confidence score is >= 90)
  2. otherwise the company's domain + its MX records (DNS over HTTPS) and
     the most common B2B pattern, first.last@domain - marked 'mx_valid', not
     'verified': the domain really receives mail, the mailbox is a best guess
Phone: only through a provider (APOLLO_API_KEY, Apollo's people/match);
without one, phone enrichment reports not found rather than guessing.
"""
from __future__ import annotations

import os
import re
import unicodedata
from typing import Any

import httpx

from db.database import get_conn

_DOMAIN_SCHEMA = {
    "type": "object",
    "properties": {"domain": {"type": ["string", "null"]}},
    "required": ["domain"],
    "additionalProperties": False,
}


def _ascii(s: str) -> str:
    return re.sub(r"[^a-z]", "", unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower())


def patterns(first: str, last: str, domain: str) -> list[str]:
    f, l = _ascii(first), _ascii(last)
    if not f:
        return []
    if not l:
        return [f"{f}@{domain}"]
    return [f"{f}.{l}@{domain}", f"{f}@{domain}", f"{f[0]}{l}@{domain}", f"{f}{l}@{domain}",
            f"{f[0]}.{l}@{domain}", f"{l}@{domain}"]


def has_mx(domain: str) -> bool:
    try:
        r = httpx.get("https://dns.google/resolve", params={"name": domain, "type": "MX"}, timeout=8)
        return any(a.get("type") == 15 for a in (r.json().get("Answer") or []))
    except Exception:  # noqa: BLE001
        return False


def find_domain(company: str) -> str | None:
    from agents.llm import json_out, research
    from outreach.prospect import _domain_is_real

    notes = research("Find a company's official website.", f"{company} official website", max_tokens=1200)
    if not notes:
        return None
    d = json_out("Extract the company's own website domain (bare, e.g. acme.com) or null.",
                 f"Company: {company}\n\n{notes}", _DOMAIN_SCHEMA, max_tokens=100).get("domain")
    if not d:
        return None
    d = d.lower().replace("https://", "").replace("http://", "").removeprefix("www.").split("/")[0]
    return d if _domain_is_real(d) else None


def _hunter(first: str, last: str, domain: str) -> tuple[str | None, str]:
    key = os.getenv("HUNTER_API_KEY")
    if not key:
        return None, "unknown"
    r = httpx.get("https://api.hunter.io/v2/email-finder",
                  params={"domain": domain, "first_name": first, "last_name": last, "api_key": key}, timeout=20)
    data = (r.json() or {}).get("data") or {}
    if data.get("email"):
        return data["email"], "verified" if (data.get("score") or 0) >= 90 else "guessed"
    return None, "not_found"


def enrich_email(contact_id: int) -> dict[str, Any]:
    with get_conn() as conn:
        c = conn.execute(
            "SELECT c.*, co.domain AS company_domain FROM sales_contacts c "
            "LEFT JOIN sales_companies co ON co.id = c.company_id WHERE c.id = %s",
            (contact_id,),
        ).fetchone()
    if not c:
        raise ValueError(f"contact {contact_id} not found")
    if c.get("email"):
        return {"email": c["email"], "email_status": c["email_status"], "email_enriched": True}
    domain = (c.get("website") or c.get("company_domain") or "").lower()
    domain = domain.replace("https://", "").replace("http://", "").removeprefix("www.").split("/")[0]
    if not domain and c.get("company"):
        try:
            domain = find_domain(c["company"]) or ""
        except Exception:  # noqa: BLE001
            domain = ""
    email, status = None, "not_found"
    if domain:
        try:
            email, status = _hunter(c.get("first_name") or "", c.get("last_name") or "", domain)
        except Exception:  # noqa: BLE001
            email, status = None, "unknown"
        if not email and has_mx(domain):
            guesses = patterns(c.get("first_name") or "", c.get("last_name") or "", domain)
            if guesses:
                email, status = guesses[0], "mx_valid"
    if not email:
        status = "not_found"
    with get_conn() as conn:
        conn.execute(
            "UPDATE sales_contacts SET email = %s, email_status = %s, email_enriched = true, "
            "website = COALESCE(website, %s), updated_at = now() WHERE id = %s",
            (email, status, domain or None, contact_id),
        )
    return {"email": email, "email_status": status, "email_enriched": True}


def enrich_phone(contact_id: int) -> dict[str, Any]:
    with get_conn() as conn:
        c = conn.execute("SELECT * FROM sales_contacts WHERE id = %s", (contact_id,)).fetchone()
    if not c:
        raise ValueError(f"contact {contact_id} not found")
    phone = c.get("phone")
    key = os.getenv("APOLLO_API_KEY")
    if not phone and key:
        try:
            r = httpx.post(
                "https://api.apollo.io/api/v1/people/match",
                headers={"X-Api-Key": key, "Content-Type": "application/json"},
                json={"linkedin_url": c.get("profile_url"), "first_name": c.get("first_name"),
                      "last_name": c.get("last_name"), "organization_name": c.get("company"),
                      "reveal_phone_number": True},
                timeout=30,
            )
            person = (r.json() or {}).get("person") or {}
            nums = person.get("phone_numbers") or []
            phone = (nums[0] or {}).get("sanitized_number") if nums else None
        except Exception:  # noqa: BLE001
            phone = None
    with get_conn() as conn:
        conn.execute("UPDATE sales_contacts SET phone = %s, phone_enriched = true, updated_at = now() WHERE id = %s",
                     (phone, contact_id))
    return {"phone": phone, "phone_enriched": True, "provider": "apollo" if key else None}
