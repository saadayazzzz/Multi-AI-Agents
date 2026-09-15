"""Query generation — the real questions a buyer asks while researching a category."""
from __future__ import annotations

from agents.llm import json_out

_SYS = (
    "You are a search-behaviour analyst. You write the exact questions real buyers "
    "type into Google or ask ChatGPT when researching a product category and "
    "choosing what to buy — natural phrasing, specific, varied in intent."
)

_SCHEMA = {
    "type": "object",
    "properties": {
        "queries": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "text": {"type": "string"},
                    "intent": {
                        "type": "string",
                        "enum": [
                            "informational", "commercial", "comparison",
                            "alternatives", "brand", "local",
                        ],
                    },
                },
                "required": ["text", "intent"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["queries"],
    "additionalProperties": False,
}


def generate_queries(
    brand: str, category: str, competitors: list[str], n: int = 24
) -> list[dict]:
    comp = ", ".join(competitors) or "none provided"
    prompt = f"""\
Category: {category}
Brand being tracked (do NOT name it in most queries — we want to see if it surfaces on its own): {brand}
Known competitors: {comp}

Write {n} distinct, realistic search queries a prospective buyer would use while
researching this category and deciding what to buy. Lowercase, no gimmicky
punctuation. Mix of intents:
- MOSTLY 'informational' / 'commercial' that name NO brand
  (e.g. "best <category> tools", "<category> for <use case>", "how to choose a <category>")
- a few 'comparison' ("<competitor a> vs <competitor b>")
- a few 'alternatives' ("<competitor> alternatives")
- 2-3 'brand' queries that DO name {brand} ("is {brand} worth it", "{brand} pricing", "{brand} reviews")
"""
    data = json_out(_SYS, prompt, _SCHEMA, max_tokens=4000)
    seen: set[str] = set()
    out: list[dict] = []
    for q in data["queries"]:
        t = q["text"].strip().lower()
        if t and t not in seen:
            seen.add(t)
            out.append({"text": t, "intent": q["intent"]})
    return out[:n]
