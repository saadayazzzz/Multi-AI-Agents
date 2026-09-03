"""Agent 1 - Discovery.

Uses Claude + hosted web search to find and rank high-quality skincare /
cosmetics e-commerce sites, then writes them to the `sites` table.
"""
from __future__ import annotations

from agents.llm import json_out, research
from agents.reporter import report
from config import settings
from db import get_conn

_SYSTEM = (
    "You are a market researcher specialising in the beauty industry. "
    "You evaluate skincare and cosmetics e-commerce websites for catalogue depth, "
    "content quality, and how well-structured their product pages are for analysis."
)

_RESEARCH_PROMPT = """\
Find the best skincare and cosmetics e-commerce websites to study as reference material.

Aim for a spread across price tiers (budget, mid, premium, luxury) and across focuses
(clean/natural, dermatological/active-ingredient, colour cosmetics, K-beauty, minimalist).

For each candidate, use web search to confirm:
- it is a live storefront that sells its own or curated products directly
- it has many product pages with real detail (ingredients, sizes, prices, descriptions)
- it is reachable without login

Return a written shortlist of about {n} sites. For each: brand name, homepage URL,
main category/focus, rough price tier, a 0-10 score for how useful it is as a
reference, and one or two sentences of rationale.
""".format(n=settings.max_sites)

_SCHEMA = {
    "type": "object",
    "properties": {
        "sites": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "url": {"type": "string"},
                    "category": {"type": "string"},
                    "price_tier": {
                        "type": "string",
                        "enum": ["budget", "mid", "premium", "luxury"],
                    },
                    "score": {"type": "number"},
                    "rationale": {"type": "string"},
                },
                "required": ["name", "url", "category", "price_tier", "score", "rationale"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["sites"],
    "additionalProperties": False,
}


def discover() -> list[dict]:
    notes = research(_SYSTEM, _RESEARCH_PROMPT, max_tokens=12000)

    data = json_out(
        _SYSTEM,
        "Convert this research shortlist into structured records. "
        "Keep only entries with a real homepage URL.\n\n" + notes,
        _SCHEMA,
    )
    sites = data["sites"][: settings.max_sites]

    stored: list[dict] = []
    with get_conn() as conn:
        for s in sites:
            url = s["url"].rstrip("/")
            row = conn.execute(
                """
                INSERT INTO sites (name, url, category, price_tier, rationale, score)
                VALUES (%(name)s, %(url)s, %(category)s, %(price_tier)s, %(rationale)s, %(score)s)
                ON CONFLICT (url) DO UPDATE SET
                    name = EXCLUDED.name,
                    category = EXCLUDED.category,
                    price_tier = EXCLUDED.price_tier,
                    rationale = EXCLUDED.rationale,
                    score = EXCLUDED.score
                RETURNING id, name, url, status
                """,
                {**s, "url": url},
            ).fetchone()
            stored.append(row)
            report(f"  [{row['id']:>3}] {row['name']}  {row['url']}", kind="status",
                   site_id=row["id"], name=row["name"], url=row["url"])

    report(f"agent1: stored {len(stored)} sites", kind="status")
    return stored


if __name__ == "__main__":
    from db import init_db

    init_db()
    discover()
