"""Agent 5 - Worldwide market pulse.

Uses Claude/OpenAI + live web search to pull the latest notable developments in
the global skincare / cosmetics market and drop them into `market_feed`. The
console streams new rows in as pop-up cards and a ticker.
"""
from __future__ import annotations

from typing import Any

from agents.llm import json_out, research
from agents.reporter import report
from db import get_conn

_SYSTEM = (
    "You are a beauty-industry market analyst. Report only real, recent, "
    "verifiable developments in the global skincare and cosmetics market. "
    "No speculation, no evergreen filler."
)

_PROMPT = """\
Using web search, list 4-6 notable developments in the WORLDWIDE skincare and
cosmetics market from roughly the last 7 days: product launches, brand M&A or
funding, retail / channel shifts, ingredient or regulation news, or macro
consumer trends.

For each: a punchy headline (<= 90 chars), a one-line detail, a tag, a rough
sentiment for the industry, the region it concerns, and the publication name.
"""

_SCHEMA = {
    "type": "object",
    "properties": {
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "headline": {"type": "string"},
                    "detail": {"type": "string"},
                    "tag": {
                        "type": "string",
                        "enum": ["launch", "trend", "m&a", "retail", "regulation", "ingredient", "macro"],
                    },
                    "sentiment": {"type": "string", "enum": ["positive", "neutral", "negative"]},
                    "region": {"type": "string"},
                    "source": {"type": "string"},
                },
                "required": ["headline", "detail", "tag", "sentiment", "region", "source"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["items"],
    "additionalProperties": False,
}


def pulse() -> int:
    """Fetch fresh market items, store the new ones, return how many were added."""
    report("agent5: scanning the worldwide beauty market…")
    notes = research(_SYSTEM, _PROMPT, max_tokens=6000)
    data = json_out(
        _SYSTEM,
        "Convert this into records. Drop anything that isn't concretely recent "
        "and attributable to a named source.\n\n" + notes,
        _SCHEMA,
        max_tokens=6000,
    )

    added = 0
    with get_conn() as conn:
        for it in data["items"]:
            row = conn.execute(
                """
                INSERT INTO market_feed (headline, detail, tag, sentiment, region, source)
                VALUES (%(headline)s, %(detail)s, %(tag)s, %(sentiment)s, %(region)s, %(source)s)
                ON CONFLICT (headline) DO NOTHING
                RETURNING id
                """,
                it,
            ).fetchone()
            if row:
                added += 1
                report(f"  • {it['headline']}", kind="status")

    report(f"agent5: {added} new market items")
    return added


if __name__ == "__main__":
    pulse()
