"""Probe engine — ask a query to an answer engine, then measure brand visibility."""
from __future__ import annotations

import re
from typing import Any

from psycopg.types.json import Jsonb

from agents.llm import json_out
from db.database import get_conn
from geo.engines import ENGINES

_URL_RE = re.compile(r"https?://[^\s\)\]\}>\"']+")

_PARSE_SYS = (
    "You analyse an answer-engine response to measure how visible a brand is. "
    "Base every judgement only on the answer text you are given."
)

_PARSE_SCHEMA = {
    "type": "object",
    "properties": {
        "brand_mentioned": {"type": "boolean"},
        "brand_position": {"type": ["integer", "null"]},
        "sentiment": {"type": ["string", "null"]},
        "brand_recommended": {"type": "boolean"},
        "competitor_mentions": {"type": "array", "items": {"type": "string"}},
    },
    "required": [
        "brand_mentioned", "brand_position", "sentiment",
        "brand_recommended", "competitor_mentions",
    ],
    "additionalProperties": False,
}


def _parse(query: str, answer: str, brand: str, domain: str | None,
           competitors: list[str]) -> dict[str, Any]:
    prompt = f"""\
QUERY: {query}

ANSWER:
{answer}

BRAND TRACKED: {brand}   (domain: {domain or 'n/a'})
COMPETITOR LIST: {', '.join(competitors) or 'none'}

From the ANSWER text only:
- brand_mentioned: is "{brand}" named anywhere in the answer?
- brand_position: among all distinct brands / products / companies named in the
  answer, in what order does "{brand}" first appear? 1 = named first. null if not mentioned.
- sentiment: the answer's overall tone toward "{brand}" — "positive", "neutral",
  "negative", or null if "{brand}" is not mentioned.
- brand_recommended: does the answer positively recommend or endorse "{brand}"
  (as opposed to merely listing or mentioning it)?
- competitor_mentions: which entries of the COMPETITOR LIST are named in the answer
  (return the exact strings from the list).
"""
    d = json_out(_PARSE_SYS, prompt, _PARSE_SCHEMA, max_tokens=2000)
    if d["sentiment"] not in ("positive", "neutral", "negative"):
        d["sentiment"] = None
    if not d["brand_mentioned"]:
        d["brand_position"] = None
    return d


def probe_query(engine: str, query_row: dict, project: dict, run_id: int,
                sample: int = 1) -> dict[str, Any]:
    answer = ENGINES[engine](query_row["text"])
    parsed = _parse(
        query_row["text"], answer, project["brand"],
        project.get("domain"), project.get("competitors") or [],
    )

    urls = list(dict.fromkeys(_URL_RE.findall(answer)))
    dom = (project.get("domain") or "").lower()
    for pre in ("https://", "http://", "www."):
        dom = dom.replace(pre, "")
    dom = dom.strip("/")
    brand_cited = bool(dom) and any(dom in u.lower() for u in urls)

    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO probes
                (run_id, query_id, engine, sample, answer, brand_mentioned,
                 brand_position, sentiment, brand_recommended, brand_cited,
                 cited_urls, competitor_mentions, raw)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                run_id, query_row["id"], engine, sample, answer,
                parsed["brand_mentioned"], parsed["brand_position"],
                parsed["sentiment"], parsed["brand_recommended"], brand_cited,
                urls, parsed["competitor_mentions"], Jsonb({"parsed": parsed}),
            ),
        )
    return {**parsed, "brand_cited": brand_cited}
