"""End-to-end: create a project -> generate queries -> probe -> score."""
from __future__ import annotations

from typing import Any

from db.database import get_conn
from geo.engines import check_engine
from geo.generate import generate_queries
from geo.probe import probe_query
from geo.score import compute_scores


def create_project(
    account: str, brand: str, category: str,
    domain: str | None = None, competitors: list[str] | None = None,
) -> int:
    competitors = competitors or []
    with get_conn() as conn:
        acc_id = conn.execute(
            "INSERT INTO accounts (name) VALUES (%s) RETURNING id", (account,)
        ).fetchone()["id"]
        pid = conn.execute(
            """
            INSERT INTO projects (account_id, brand, domain, competitors, topics)
            VALUES (%s, %s, %s, %s, %s) RETURNING id
            """,
            (acc_id, brand, domain, competitors, [category]),
        ).fetchone()["id"]
    return pid


def gen_queries(project_id: int, n: int = 24) -> list[dict]:
    with get_conn() as conn:
        p = conn.execute("SELECT * FROM projects WHERE id = %s", (project_id,)).fetchone()
    if not p:
        raise SystemExit(f"no project {project_id}")
    category = (p["topics"] or ["general"])[0]

    qs = generate_queries(p["brand"], category, p["competitors"], n=n)
    with get_conn() as conn:
        for q in qs:
            conn.execute(
                "INSERT INTO queries (project_id, text, intent, source) "
                "VALUES (%s, %s, %s, 'generated') "
                "ON CONFLICT (project_id, text) DO NOTHING",
                (project_id, q["text"], q["intent"]),
            )
        rows = conn.execute(
            "SELECT id, text, intent FROM queries WHERE project_id = %s AND active "
            "ORDER BY id",
            (project_id,),
        ).fetchall()
    return rows


def run_probe(
    project_id: int, engine: str = "openai", samples: int = 1, limit: int | None = None
) -> tuple[int, dict[str, Any]]:
    check_engine(engine)
    with get_conn() as conn:
        proj = conn.execute("SELECT * FROM projects WHERE id = %s", (project_id,)).fetchone()
        qs = conn.execute(
            "SELECT id, text, intent FROM queries WHERE project_id = %s AND active "
            "ORDER BY id",
            (project_id,),
        ).fetchall()
        if limit:
            qs = qs[:limit]
        if not qs:
            raise SystemExit("no queries — run `geo gen-queries <project>` first")
        run_id = conn.execute(
            "INSERT INTO probe_runs (project_id, engine) VALUES (%s, %s) RETURNING id",
            (project_id, engine),
        ).fetchone()["id"]

    total = len(qs) * samples
    print(f"geo: run {run_id} — {len(qs)} queries x {samples} sample(s) = {total} probes on '{engine}'")
    done = 0
    for q in qs:
        for s in range(1, samples + 1):
            done += 1
            try:
                r = probe_query(engine, q, proj, run_id, s)
                mark = "HIT " if r["brand_mentioned"] else "miss"
                pos = f" #{r['brand_position']}" if r["brand_position"] else ""
                print(f"  [{done}/{total}] {mark}{pos}  {q['text'][:64]}")
            except Exception as e:  # noqa: BLE001
                print(f"  [{done}/{total}] ERR  {q['text'][:48]} -- {e}")

    with get_conn() as conn:
        conn.execute(
            "UPDATE probe_runs SET status = 'done', finished_at = now() WHERE id = %s",
            (run_id,),
        )

    sc = compute_scores(run_id)
    print(
        f"\ngeo: VISIBILITY SCORE  {sc['score']}/100\n"
        f"  presence {sc['presence_rate']:.0%}  |  cited {sc['citation_rate']:.0%}  |  "
        f"recommended {sc['reco_rate']:.0%}  |  share-of-voice {sc['share_of_voice']:.0%}"
        + (f"  |  avg position {sc['avg_position']}" if sc["avg_position"] else "")
    )
    if sc["per_competitor_hits"]:
        ranked = sorted(sc["per_competitor_hits"].items(), key=lambda kv: -kv[1])
        print("  competitors: " + ", ".join(f"{k} {v}" for k, v in ranked))
    return run_id, sc
