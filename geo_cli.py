"""AI Search Visibility (GEO) — CLI.

    python geo_cli.py initdb
    python geo_cli.py new-project --account "Acme" --brand "Ahrefs" \
        --category "SEO tools" --domain ahrefs.com \
        --competitors "Semrush, Moz, SE Ranking, Ubersuggest"
    python geo_cli.py gen-queries 1 -n 24
    python geo_cli.py probe 1 --engine openai --samples 1 --limit 8
"""
from __future__ import annotations

import argparse
import sys

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from db.database import wait_for_db
from geo.db import init_geo_db
from geo.pipeline import create_project, gen_queries, run_probe


def main() -> None:
    ap = argparse.ArgumentParser(prog="geo")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("initdb")

    np = sub.add_parser("new-project")
    np.add_argument("--account", required=True)
    np.add_argument("--brand", required=True)
    np.add_argument("--category", required=True)
    np.add_argument("--domain")
    np.add_argument("--competitors", default="", help="comma-separated")

    gq = sub.add_parser("gen-queries")
    gq.add_argument("project", type=int)
    gq.add_argument("-n", type=int, default=24)

    rp = sub.add_parser("probe")
    rp.add_argument("project", type=int)
    rp.add_argument("--engine", default="openai")
    rp.add_argument("--samples", type=int, default=1)
    rp.add_argument("--limit", type=int)

    args = ap.parse_args()
    wait_for_db()
    init_geo_db()

    if args.cmd == "initdb":
        return

    if args.cmd == "new-project":
        comps = [c.strip() for c in args.competitors.split(",") if c.strip()]
        pid = create_project(args.account, args.brand, args.category, args.domain, comps)
        print(f"project {pid} created  ({args.brand} vs {', '.join(comps) or 'no competitors'})")

    elif args.cmd == "gen-queries":
        rows = gen_queries(args.project, args.n)
        print(f"{len(rows)} queries for project {args.project}:")
        for r in rows:
            print(f"  [{r['intent']:>12}]  {r['text']}")

    elif args.cmd == "probe":
        run_probe(args.project, args.engine, args.samples, args.limit)


if __name__ == "__main__":
    main()
