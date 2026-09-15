"""Outbound sales engine — CLI.

    python outreach_cli.py initdb
    python outreach_cli.py campaign \
        --name "GEO audits" \
        --icp "B2B SaaS companies (Series A-C, 20-200 staff) in project management, \
CRM, or marketing software, US/UK, with an active content/SEO team" \
        --offer "I run your brand through the AI answer engines your buyers use \
(ChatGPT, Perplexity, Google AI Overviews) and show where you're invisible or \
losing to competitors, plus the fixes. First audit is free." \
        --from-name "Saad" --from-email you@yourdomain.com --daily-cap 20
    python outreach_cli.py cycle 1 --prospect 6 --geo-queries 6         # draft only
    python outreach_cli.py cycle 1 --prospect 6 --geo-queries 6 --send  # + email (needs SMTP_*)
    python outreach_cli.py leads 1
    python outreach_cli.py export 1
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
from outreach.db import init_outreach_db
from outreach.excel import export_xlsx
from outreach.pipeline import create_campaign, run_cycle


def main() -> None:
    ap = argparse.ArgumentParser(prog="outreach")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("initdb")

    cp = sub.add_parser("campaign")
    cp.add_argument("--name", required=True)
    cp.add_argument("--icp", required=True)
    cp.add_argument("--offer", required=True)
    cp.add_argument("--from-name")
    cp.add_argument("--from-email")
    cp.add_argument("--daily-cap", type=int, default=20)

    cy = sub.add_parser("cycle")
    cy.add_argument("campaign", type=int)
    cy.add_argument("--prospect", type=int, default=8)
    cy.add_argument("--geo-queries", type=int, default=6)
    cy.add_argument("--send", action="store_true")

    lp = sub.add_parser("leads")
    lp.add_argument("campaign", type=int)

    ep = sub.add_parser("export")
    ep.add_argument("campaign", type=int)
    ep.add_argument("--out", default="leads.xlsx")

    args = ap.parse_args()
    wait_for_db()
    init_geo_db()
    init_outreach_db()

    if args.cmd == "initdb":
        return

    if args.cmd == "campaign":
        cid = create_campaign(
            args.name, args.icp, args.offer,
            args.from_name, args.from_email, args.daily_cap,
        )
        print(f"campaign {cid} created")

    elif args.cmd == "cycle":
        run_cycle(args.campaign, args.prospect, args.geo_queries, args.send)

    elif args.cmd == "leads":
        from db.database import get_conn

        with get_conn() as conn:
            rows = conn.execute(
                "SELECT company, domain, contact_role, contact_email, geo_score, "
                "status FROM leads WHERE campaign_id = %s ORDER BY id",
                (args.campaign,),
            ).fetchall()
        for r in rows:
            print(
                f"  {r['status']:<9} {str(r['geo_score'] or '-'):<6} "
                f"{r['company']:<28} {r['contact_email'] or ''}"
            )

    elif args.cmd == "export":
        print("wrote", export_xlsx(args.campaign, args.out))


if __name__ == "__main__":
    main()
