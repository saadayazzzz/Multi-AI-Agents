"""Turn a theme into clip prompts + YouTube metadata."""
from __future__ import annotations

from agents.llm import json_out

_SYS = (
    "You direct short, satisfying / ASMR 'objects cutting' videos. You write prompts "
    "for a text-to-video model and metadata for YouTube in the oddly-satisfying niche."
)

_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "description": {"type": "string"},
        "tags": {"type": "array", "items": {"type": "string"}},
        "clips": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"object": {"type": "string"}, "prompt": {"type": "string"}},
                "required": ["object", "prompt"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["title", "description", "tags", "clips"],
    "additionalProperties": False,
}


def script(theme: str, n: int) -> dict:
    prompt = f"""\
Theme: {theme}

Write {n} distinct clip prompts for an AI video model. Every clip is the SAME shot type:
- extreme macro close-up, shallow depth of field, soft even studio lighting, clean
  seamless background
- a very sharp knife (or thin blade / hot wire) slowly and cleanly slices through ONE
  object resting on a clean surface; the object splits and its inside is revealed
- no people, no text, no logos; at most a single gloved hand holding the knife
- crisp, ASMR-friendly, slightly slow-motion feel; consistent style across all clips
Each clip must use a DIFFERENT object, chosen to look extremely satisfying to cut
(vary textures: soft, crystalline, layered, foamy, gel, etc.).

Also produce YouTube metadata:
- title: <= 70 chars, includes "ASMR" and "satisfying", no ALL CAPS
- description: 2-3 short lines, ends with "#satisfying #ASMR #oddlysatisfying"
- tags: 12-15 lowercase tags for this niche
"""
    return json_out(_SYS, prompt, _SCHEMA, max_tokens=3000)
