"""Visibility score — turns a probe run into one 0-100 number + the breakdown."""
from __future__ import annotations

from typing import Any

from psycopg.types.json import Jsonb

from db.database import get_conn

# how much a mention is worth by the order the brand is named in the answer
_POS_WEIGHT = {1: 1.0, 2: 0.75, 3: 0.55, 4: 0.4}


def _pos_weight(pos: int | None) -> float:
    if pos is None:
        return 0.5  # mentioned but not clearly ranked
    return _POS_WEIGHT.get(pos, 0.25)


def compute_scores(run_id: int) -> dict[str, Any] | None:
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT brand_mentioned, brand_position, brand_cited, brand_recommended,
                   competitor_mentions, engine
            FROM probes WHERE run_id = %s
            """,
            (run_id,),
        ).fetchall()
        proj = conn.execute(
            "SELECT p.* FROM probe_runs r JOIN projects p ON p.id = r.project_id "
            "WHERE r.id = %s",
            (run_id,),
        ).fetchone()

    if not rows:
        return None

    n = len(rows)
    present = [r for r in rows if r["brand_mentioned"]]
    ranked = [r["brand_position"] for r in present if r["brand_position"]]

    presence_rate = len(present) / n
    weighted_presence = sum(
        _pos_weight(r["brand_position"]) if r["brand_mentioned"] else 0.0 for r in rows
    ) / n
    citation_rate = sum(1 for r in rows if r["brand_cited"]) / n
    reco_rate = sum(1 for r in rows if r["brand_recommended"]) / n
    avg_position = (sum(ranked) / len(ranked)) if ranked else None

    brand_hits = len(present)
    comp_hits = sum(len(r["competitor_mentions"] or []) for r in rows)
    sov = brand_hits / (brand_hits + comp_hits) if (brand_hits + comp_hits) else 0.0

    score = 100 * (
        0.40 * weighted_presence
        + 0.15 * citation_rate
        + 0.15 * reco_rate
        + 0.30 * sov
    )

    per_comp = {
        c: sum(1 for r in rows if c in (r["competitor_mentions"] or []))
        for c in (proj["competitors"] or [])
    }
    detail = {"per_competitor_hits": per_comp, "brand_hits": brand_hits, "n": n}

    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO visibility_scores
                (project_id, run_id, engine, presence_rate, avg_position,
                 citation_rate, reco_rate, share_of_voice, score, detail)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                proj["id"], run_id, rows[0]["engine"], presence_rate, avg_position,
                citation_rate, reco_rate, sov, score, Jsonb(detail),
            ),
        )

    return {
        "score": round(score, 1),
        "presence_rate": round(presence_rate, 3),
        "citation_rate": round(citation_rate, 3),
        "reco_rate": round(reco_rate, 3),
        "share_of_voice": round(sov, 3),
        "avg_position": round(avg_position, 2) if avg_position else None,
        "per_competitor_hits": per_comp,
        "n": n,
    }
