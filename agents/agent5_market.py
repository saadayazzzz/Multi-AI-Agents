"""Agent 5 - AI-search / GEO industry pulse.

Uses the model + live web search to pull the latest notable developments in the
AI-search and generative-engine-optimization (GEO) space and drop them into
`market_feed`. The console streams new rows in as pop-up callouts and a ticker.
"""
from __future__ import annotations

from typing import Any

from agents.llm import json_out, research
from agents.reporter import report
from db import get_conn

_SYSTEM = (
    "You are an analyst covering the AI-search and generative-engine-optimization "
    "(GEO) industry. Report only real, recent, verifiable developments. "
    "No speculation, no evergreen filler."
)

_PROMPT = """\
Using web search, list 4-6 notable developments from roughly the last 7 days in
the AI-search / GEO space:
- answer-engine changes: ChatGPT, Perplexity, Google AI Overviews / AI Mode,
  Gemini, Copilot — new features, citation/linking behaviour, ad or shopping
  moves, policy changes
- AI-search adoption, traffic or market-share shifts vs traditional search
- GEO / AI-visibility tools: launches, funding, acquisitions, major updates
- studies or data on how LLMs pick and cite sources, or on brand visibility in
  AI answers
- publisher licensing deals, copyright or regulation news affecting AI search
- a concrete GEO tactic that's newly working

For each: a punchy headline (<= 90 chars), a one-line detail, a tag, a rough
sentiment for brands trying to stay visible, the region it concerns, and the
publication name.
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
                        "enum": [
                            "platform", "shift", "tool", "funding",
                            "study", "regulation", "tactic",
                        ],
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
    """Fetch fresh AI-search / GEO items, store the new ones, return how many were added."""
    report("agent5: scanning the AI-search / GEO industry…")
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

    report(f"agent5: {added} new AI-search / GEO items")
    return added


if __name__ == "__main__":
    pulse()
