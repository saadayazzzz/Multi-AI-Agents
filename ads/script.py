"""niche/product -> ad script: hook, full voiceover script, and B-roll prompts."""
from __future__ import annotations

from typing import Any

from agents.llm import json_out

_SYSTEM = (
    "You write scripts for faceless AI UGC-style short ads (TikTok/Reels/"
    "Shorts, 9:16, 20-40 seconds spoken). No on-camera person, no talking "
    "head - just a voiceover over B-roll. Sound like a real person sharing a "
    "genuine find, not an ad: a pattern-interrupt hook in the first line, "
    "short punchy sentences written to be read aloud, one concrete benefit "
    "or result, and a soft CTA at the end (follow for more / link in bio / "
    "try it yourself - never pushy).\n\n"
    "Writing visual_prompts: the image model behind this is free and "
    "unreliable on two things - (1) legible on-screen content: any request "
    "for a UI, dashboard, chart, or on-screen text comes out an illegible "
    "smear, so never describe on-screen content; (2) complex human anatomy: "
    "wide shots of full bodies, faces mid-expression, or unusual poses often "
    "come out warped, so avoid describing a person's face or pose in detail. "
    "Strongly prefer close-up shots of hands, products, objects, textures, "
    "and simple everyday settings - things a camera photographs reliably. If "
    "a person must appear, keep it to hands/shoulders only, doing one simple "
    "action (holding, pouring, tapping), in bright even lighting, vertical "
    "framing, one clear subject per prompt."
)

_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string", "description": "internal reference title"},
        "hook": {"type": "string", "description": "the first spoken line, <=12 words"},
        "script": {"type": "string", "description": "the full voiceover script, spoken naturally"},
        "description": {"type": "string", "description": "YouTube Shorts description"},
        "tags": {"type": "array", "items": {"type": "string"}},
        "hashtags": {"type": "array", "items": {"type": "string"}},
        "visual_prompts": {
            "type": "array",
            "items": {"type": "string"},
            "description": "4-7 B-roll image prompts covering the whole script in order",
        },
    },
    "required": ["title", "hook", "script", "description", "tags", "hashtags", "visual_prompts"],
    "additionalProperties": False,
}


def script(niche: str, product: str | None = None, seconds: int = 30) -> dict[str, Any]:
    subject = f"{product} ({niche})" if product else niche
    user = (
        f"Write a {seconds}-second faceless AI UGC ad script for: {subject}.\n"
        "Split the visuals into 4-7 B-roll prompts, roughly evenly spaced "
        "across the script's runtime, each depicting a real physical scene "
        "relevant to that part of the script."
    )
    return json_out(_SYSTEM, user, _SCHEMA, max_tokens=2000)
