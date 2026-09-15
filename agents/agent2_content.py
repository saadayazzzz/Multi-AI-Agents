"""Agent 2 - Content Studio.

Turns a trend (or an ad-hoc topic) into a platform-native piece of content:
a script for YouTube, a caption for Instagram, a post body for LinkedIn -
plus hashtags, a CTA, and a thumbnail prompt for Agent 3 to render.
"""
from __future__ import annotations

from typing import Any

from psycopg.types.json import Jsonb

from agents.llm import json_out
from agents.reporter import report
from db import get_conn

_SYSTEM = (
    "You are the content strategist and copywriter for a solo builder who "
    "creates custom AI agents and automation systems for businesses - an 'AI "
    "agency of one', building in public. You write scroll-stopping, "
    "platform-native content in a real human voice - never corporate, never "
    "generic hashtag spam, never opens with filler like 'In today's world...' "
    "or 'Have you ever wondered...'.\n\n"
    "Every hook must use a proven high-retention pattern: a pattern-interrupt "
    "opening line, a curiosity gap, a bold or contrarian claim, a concrete "
    "number/result, or a sharp relatable pain point - something that stops the "
    "scroll in the first line.\n\n"
    "The content builds authority in AI agents/automation (build-in-public "
    "updates, demos of things built, mistakes businesses make with off-the-"
    "shelf AI tools, before/after automation stories, contrarian takes on AI "
    "hype). Only occasionally (roughly 1 in 4 posts) end with a direct CTA "
    "inviting the reader to DM or book a call about building their own AI "
    "agent - the rest should build trust with pure value, no hard sell.\n\n"
    "Writing thumbnail_prompt: image models (including the free one this "
    "pipeline uses) cannot render legible screens - any request for a laptop/"
    "phone screen showing a UI, dashboard, chart, flowchart, code, or diagram "
    "comes out as an illegible abstract smear. Never describe on-screen "
    "content. Instead describe a real physical scene: a person at a desk, "
    "hands on a keyboard, a closed or blank/glowing laptop screen, an office "
    "or workspace, objects, lighting, mood - things a camera actually "
    "photographs well. Keep it concrete and simple, one clear subject."
)

_SCHEMAS: dict[str, dict] = {
    "youtube": {
        "type": "object",
        "properties": {
            "title": {"type": "string"},
            "script": {"type": "string"},
            "description": {"type": "string"},
            "tags": {"type": "array", "items": {"type": "string"}},
            "hashtags": {"type": "array", "items": {"type": "string"}},
            "cta": {"type": "string"},
            "thumbnail_prompt": {"type": "string"},
        },
        "required": ["title", "script", "description", "tags", "hashtags", "cta", "thumbnail_prompt"],
        "additionalProperties": False,
    },
    "instagram": {
        "type": "object",
        "properties": {
            "caption": {"type": "string"},
            "hashtags": {"type": "array", "items": {"type": "string"}},
            "cta": {"type": "string"},
            "thumbnail_prompt": {"type": "string"},
        },
        "required": ["caption", "hashtags", "cta", "thumbnail_prompt"],
        "additionalProperties": False,
    },
    "linkedin": {
        "type": "object",
        "properties": {
            "title": {"type": "string"},
            "body": {"type": "string"},
            "hashtags": {"type": "array", "items": {"type": "string"}},
            "cta": {"type": "string"},
            "thumbnail_prompt": {"type": "string"},
        },
        "required": ["title", "body", "hashtags", "cta", "thumbnail_prompt"],
        "additionalProperties": False,
    },
}

_PROMPTS: dict[str, str] = {
    "youtube": (
        "Trending format/hook style to use: {topic}\nSuggested angle: {angle}\n\n"
        "Write a YouTube Short script that applies this format to MY AI-agent-"
        "building work (a demo of something I built, a mistake founders make "
        "with off-the-shelf AI tools, a before/after automation story, or a "
        "sharp take on AI agent hype). Hook must land in the first 3 seconds. "
        "Tight spoken script (30-60s when read aloud), a title (<=60 chars), "
        "an SEO description, 10-15 tags, 3-5 hashtags, a CTA (see the value-"
        "vs-pitch ratio in your instructions), and an image prompt describing "
        "an eye-catching thumbnail (no text baked into the image)."
    ),
    "instagram": (
        "Trending format/hook style to use: {topic}\nSuggested angle: {angle}\n\n"
        "Write an Instagram Reel/post caption that applies this format to MY "
        "AI-agent-building work (a demo, a build-in-public update, a mistake "
        "businesses make with off-the-shelf AI, or a sharp take on AI agent "
        "hype). Hook in the first line, punchy and scannable, 3-8 relevant "
        "hashtags (no spammy over-tagging), a CTA (see the value-vs-pitch "
        "ratio in your instructions), and an image prompt for an eye-catching "
        "cover image (no text baked into the image)."
    ),
    "linkedin": (
        "Trending format/hook style to use: {topic}\nSuggested angle: {angle}\n\n"
        "Write a LinkedIn post that applies this format to MY AI-agent-"
        "building work (a build-in-public update, a demo, a mistake founders "
        "make with off-the-shelf AI tools, or a sharp take on AI agent hype). "
        "Human voice, a strong pattern-interrupt opening line (not corporate), "
        "short punchy paragraphs, a title for internal reference, 3-5 "
        "hashtags, a CTA (see the value-vs-pitch ratio in your instructions), "
        "and an image prompt for a professional cover image (no text baked "
        "into the image)."
    ),
}


def _pick_trend(conn, platform: str, topic: str | None, trend_id: int | None) -> dict | None:
    if trend_id:
        return conn.execute("SELECT * FROM trends WHERE id = %s", (trend_id,)).fetchone()
    if topic:
        return None
    return conn.execute(
        "SELECT * FROM trends WHERE platform = %s AND status = 'new' "
        "ORDER BY score DESC NULLS LAST, created_at DESC LIMIT 1",
        (platform,),
    ).fetchone()


def write(platform: str, topic: str | None = None, trend_id: int | None = None) -> dict[str, Any]:
    if platform not in _SCHEMAS:
        raise ValueError(f"unknown platform: {platform}")

    with get_conn() as conn:
        trend = _pick_trend(conn, platform, topic, trend_id)
        if trend:
            topic, angle = trend["topic"], trend["angle"]
        elif not topic:
            raise RuntimeError(
                f"no topic given and no unused trends found for {platform} - run find_trends first"
            )
        else:
            angle = "your own angle"

        data = json_out(
            _SYSTEM,
            _PROMPTS[platform].format(topic=topic, angle=angle),
            _SCHEMAS[platform],
            max_tokens=4000,
        )
        thumbnail_prompt = data.pop("thumbnail_prompt")
        title = data.get("title") or (topic[:80] if topic else None)

        row = conn.execute(
            """
            INSERT INTO content_pieces
                (trend_id, platform, title, script, caption, hashtags, cta, extra)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id, platform, title
            """,
            (
                trend["id"] if trend else None,
                platform,
                title,
                data.get("script"),
                data.get("caption") or data.get("body"),
                data.get("hashtags"),
                data.get("cta"),
                Jsonb({**{k: v for k, v in data.items() if k not in ("hashtags", "cta")},
                       "thumbnail_prompt": thumbnail_prompt}),
            ),
        ).fetchone()

        if trend:
            conn.execute("UPDATE trends SET status = 'used' WHERE id = %s", (trend["id"],))

    report(f"agent2: drafted {platform} content #{row['id']}: {row['title']}", kind="status",
           content_id=row["id"], platform=platform)
    return row


if __name__ == "__main__":
    from db import init_db

    init_db()
    write("linkedin")
