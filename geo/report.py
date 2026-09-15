"""Formatted scorecard for a project's latest probe run."""
from __future__ import annotations

from db.database import get_conn


def _bar(n: int, top: int, width: int = 24) -> str:
    fill = 0 if top == 0 else round(width * n / top)
    return "#" * fill + "-" * (width - fill)


def print_report(project_id: int) -> None:
    with get_conn() as conn:
        proj = conn.execute("SELECT * FROM projects WHERE id = %s", (project_id,)).fetchone()
        if not proj:
            raise SystemExit(f"no project {project_id}")
        run = conn.execute(
            "SELECT * FROM probe_runs WHERE project_id = %s AND status = 'done' "
            "ORDER BY id DESC LIMIT 1",
            (project_id,),
        ).fetchone()
        if not run:
            raise SystemExit("no completed run — run `geo probe` first")
        sc = conn.execute(
            "SELECT * FROM visibility_scores WHERE run_id = %s ORDER BY id DESC LIMIT 1",
            (run["id"],),
        ).fetchone()
        rows = conn.execute(
            """
            SELECT q.text, q.intent, p.brand_mentioned, p.brand_position,
                   p.sentiment, p.brand_recommended, p.brand_cited, p.competitor_mentions
            FROM probes p JOIN queries q ON q.id = p.query_id
            WHERE p.run_id = %s ORDER BY p.id
            """,
            (run["id"],),
        ).fetchall()

    brand = proj["brand"]
    line = "=" * 78
    print(f"\n{line}\n  AI SEARCH VISIBILITY  ·  {brand}  ({proj['domain'] or 'no domain'})")
    print(f"  engine: {run['engine']}   run #{run['id']}   {run['finished_at']:%Y-%m-%d %H:%M}")
    print(line)
    print(f"  SCORE  {float(sc['score']):.1f} / 100")
    print(
        f"  presence {float(sc['presence_rate']):.0%}   "
        f"cited {float(sc['citation_rate']):.0%}   "
        f"recommended {float(sc['reco_rate']):.0%}   "
        f"share-of-voice {float(sc['share_of_voice']):.0%}"
        + (f"   avg position {float(sc['avg_position']):.1f}" if sc["avg_position"] else "")
    )
    print(line)
    print(f"  {'INTENT':<8} {'RESULT':<10} {'SENT':<9} QUERY")
    for r in rows:
        if r["brand_mentioned"]:
            pos = f"#{r['brand_position']}" if r["brand_position"] else "-"
            res = f"HIT {pos}" + ("*" if r["brand_recommended"] else "")
        else:
            res = "miss"
        intent = (r["intent"] or "")[:8]
        print(f"  {intent:<8} {res:<10} {(r['sentiment'] or '-'):<9} {r['text'][:48]}")

    # competitor leaderboard
    tally = {brand: sum(1 for r in rows if r["brand_mentioned"])}
    for c in proj["competitors"] or []:
        tally[c] = sum(1 for r in rows if c in (r["competitor_mentions"] or []))
    top = max(tally.values()) if tally else 0
    print(line)
    print("  SHARE OF VOICE (mentions across queries)")
    for name, n in sorted(tally.items(), key=lambda kv: -kv[1]):
        star = "  <- you" if name == brand else ""
        print(f"    {name:<16} {_bar(n, top)} {n}{star}")
    print(f"{line}\n")
