"""Agent 1 - Trend Scout.

Uses live web search to find what's currently trending on YouTube, Instagram,
and LinkedIn, then writes structured trend rows so Agent 2 (Content Studio)
can turn them into scripts/captions.
"""
from __future__ import annotations

from agents.llm import json_out, research
from agents.reporter import report
from db import get_conn

_PLATFORMS = ["youtube", "instagram", "linkedin"]

_SYSTEM = (
    "You are a social media trend analyst for a solo builder who creates "
    "custom AI agents/automation for businesses (an 'AI agency of one', "
    "build-in-public style). You track what's actually working right now on "
    "YouTube, Instagram, and LinkedIn - real formats and hooks getting "
    "traction with a tech/founder/builder/SaaS audience this week, not "
    "generic evergreen advice."
)

_RESEARCH_PROMPT = """\
Using web search, find 5-8 things trending RIGHT NOW on {platform} that a solo
AI-agent/automation builder could use as a FORMAT or HOOK STYLE this week -
things resonating with a tech/founder/builder/SaaS/AI audience: trending
video/post formats, hook styles, storytelling structures, or discourse (e.g.
"day in the life of building X", "I automated my business's Y", build-in-
public updates, tool teardown/reaction formats, contrarian AI takes).

We care about the FORMAT and HOOK STYLE that's working, not the topic itself -
Agent 2 will apply it to our own AI-agent-building niche. For each: the
format/hook pattern, the content angle to apply it, the best content type for
{platform} (e.g. short-form video, carousel, text post, thread), why it's hot
right now, and a rough 0-10 score for how strong the opportunity is.
"""

_SCHEMA = {
    "type": "object",
    "properties": {
        "trends": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "topic": {"type": "string"},
                    "angle": {"type": "string"},
                    "format": {"type": "string"},
                    "rationale": {"type": "string"},
                    "score": {"type": "number"},
                    "source": {"type": "string"},
                },
                "required": ["topic", "angle", "format", "rationale", "score", "source"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["trends"],
    "additionalProperties": False,
}


def scout(platform: str | None = None) -> list[dict]:
    platforms = [platform] if platform else _PLATFORMS
    stored: list[dict] = []

    with get_conn() as conn:
        for p in platforms:
            notes = research(_SYSTEM, _RESEARCH_PROMPT.format(platform=p), max_tokens=8000)
            data = json_out(
                _SYSTEM,
                f"Convert this into structured trend records for {p}.\n\n" + notes,
                _SCHEMA,
                max_tokens=4000,
            )
            for it in data["trends"]:
                row = conn.execute(
                    """
                    INSERT INTO trends (platform, topic, angle, format, rationale, score, source)
                    VALUES (%(platform)s, %(topic)s, %(angle)s, %(format)s, %(rationale)s, %(score)s, %(source)s)
                    ON CONFLICT (platform, topic) DO UPDATE SET
                        angle = EXCLUDED.angle,
                        format = EXCLUDED.format,
                        rationale = EXCLUDED.rationale,
                        score = EXCLUDED.score,
                        source = EXCLUDED.source,
                        status = 'new'
                    RETURNING id, platform, topic
                    """,
                    {**it, "platform": p},
                ).fetchone()
                stored.append(row)
                report(f"  [{p}] {row['topic']}", kind="status", platform=p, trend_id=row["id"])

    report(f"agent1: stored {len(stored)} trends across {platforms}", kind="status")
    return stored


if __name__ == "__main__":
    from db import init_db

    init_db()
    scout()
