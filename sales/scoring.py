"""Lead scoring on Gojiberry's 0-3 scale: persona + company + intent.

- persona (0-1): does their role match the agent's target job titles?
- company (0-1): industry / size / location / company type fit.
- intent  (0-1): how strong and how fresh the signal that found them is.

persona and company come from one batched LLM call per ~15 candidates
(it reads the headline and evidence the same way a human SDR would);
intent is pure arithmetic on the signal type and its age. An agent's
min_lead_score (0-1) is compared against total / 3.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

from sales.constants import SIGNALS

_SYS = (
    "You are a strict B2B lead qualifier. For each candidate, judge from their "
    "LinkedIn headline and the evidence how well they match the target profile. "
    "Be calibrated: 1.0 = clearly matches, 0.5 = plausible but unclear, 0 = clearly "
    "not. Flag service providers (agencies, consultants, freelancers, outsourcing / "
    "dev shops, coaches selling services) - they are competitors or vendors, not buyers. "
    "Infer job title, company, industry, location and company size only from what the "
    "text supports; use null when it doesn't say."
)

_SCHEMA = {
    "type": "object",
    "properties": {
        "leads": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "i": {"type": "integer"},
                    "persona": {"type": "number"},
                    "company": {"type": "number"},
                    "service_provider": {"type": "boolean"},
                    "job_title": {"type": ["string", "null"]},
                    "company_name": {"type": ["string", "null"]},
                    "industry": {"type": ["string", "null"]},
                    "location": {"type": ["string", "null"]},
                    "company_size": {"type": ["string", "null"]},
                    "reason": {"type": "string"},
                },
                "required": ["i", "persona", "company", "service_provider", "job_title",
                             "company_name", "industry", "location", "company_size", "reason"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["leads"],
    "additionalProperties": False,
}


def icp_text(agent: dict) -> str:
    parts = []
    for label, key in (
        ("Job titles", "target_job_titles"), ("Industries", "target_industries"),
        ("Company sizes (employees)", "target_company_sizes"), ("Locations", "target_locations"),
        ("Company types", "target_company_types"),
    ):
        if agent.get(key):
            parts.append(f"{label}: {', '.join(agent[key])}")
    if agent.get("additional_criteria"):
        parts.append(f"Also: {agent['additional_criteria']}")
    return "\n".join(parts) or "Any B2B decision-maker"


def intent_score(c: dict[str, Any], now: datetime | None = None) -> float:
    base = SIGNALS.get(c.get("intent_type") or "", (0.5,))[0]
    at = c.get("intent_at")
    if not at:
        return round(base * 0.8, 3)
    try:
        when = at if isinstance(at, datetime) else datetime.fromisoformat(str(at).replace("Z", "+00:00"))
        if when.tzinfo is None:
            when = when.replace(tzinfo=timezone.utc)
    except ValueError:
        return round(base * 0.8, 3)
    age = max(0.0, ((now or datetime.now(timezone.utc)) - when).total_seconds() / 86400)
    return round(base * max(0.4, 1 - age / 60), 3)


def _words(s: str) -> set[str]:
    return {w for w in re.findall(r"[a-z]+", (s or "").lower()) if len(w) > 1}


def heuristic_persona(c: dict, titles: list[str]) -> float:
    """Fallback when the LLM is unavailable: title word overlap."""
    if not titles:
        return 0.6
    text = _words((c.get("job_title") or "") + " " + (c.get("headline") or ""))
    best = 0.0
    for t in titles:
        tw = _words(t)
        if tw and tw <= text:
            return 1.0
        if tw:
            best = max(best, len(tw & text) / len(tw))
    return round(0.2 + 0.6 * best, 3)


def score_candidates(agent: dict, cands: list[dict], batch: int = 15) -> list[dict]:
    """Returns the candidates with `scoring`, `total_score` and
    `service_provider` filled in (and inferred fields backfilled)."""
    if not cands:
        return []
    if agent.get("skip_icp_filter"):
        for c in cands:
            c["scoring"] = {"persona": 1.0, "company": 1.0, "intent": intent_score(c), "reason": "ICP filter skipped"}
            c["service_provider"] = False
            c["total_score"] = round(2 + c["scoring"]["intent"], 3)
        return cands

    from agents.llm import json_out

    icp = icp_text(agent)
    for start in range(0, len(cands), batch):
        chunk = cands[start:start + batch]
        lines = []
        for i, c in enumerate(chunk):
            lines.append(
                f"[{i}] {c.get('full_name')} | headline: {c.get('headline') or c.get('job_title') or '?'} | "
                f"company: {c.get('company') or '?'} | location: {c.get('location') or '?'} | "
                f"evidence: {(c.get('intent') or '')[:400]}"
            )
        try:
            data = json_out(
                _SYS,
                f"TARGET PROFILE\n{icp}\n\nCANDIDATES\n" + "\n".join(lines) +
                "\n\nScore every candidate by its index.",
                _SCHEMA, max_tokens=4000,
            )
            by_i = {r["i"]: r for r in data.get("leads", [])}
        except Exception:  # noqa: BLE001 - scoring must degrade, not crash the run
            by_i = {}
        for i, c in enumerate(chunk):
            r = by_i.get(i)
            if r:
                persona = min(1.0, max(0.0, float(r["persona"])))
                company = min(1.0, max(0.0, float(r["company"])))
                for src, dst in (("job_title", "job_title"), ("company_name", "company"),
                                 ("industry", "industry"), ("location", "location")):
                    if r.get(src) and not c.get(dst):
                        c[dst] = r[src]
                c["company_size"] = r.get("company_size")
                c["service_provider"] = bool(r["service_provider"])
                reason = r["reason"]
            else:
                persona = heuristic_persona(c, agent.get("target_job_titles") or [])
                company = 0.5
                c["service_provider"] = False
                reason = "heuristic (LLM scoring unavailable)"
            intent = intent_score(c)
            c["scoring"] = {"persona": round(persona, 3), "company": round(company, 3),
                            "intent": intent, "reason": reason}
            c["total_score"] = round(persona + company + intent, 3)
    return cands


def passes(agent: dict, c: dict) -> bool:
    return float(c.get("total_score") or 0) / 3 >= float(agent.get("min_lead_score") or 0)
