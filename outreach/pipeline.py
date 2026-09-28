"""One cycle: prospect -> enrich -> visibility-score -> draft -> (send) -> export."""
from __future__ import annotations

from typing import Any

from agents.reporter import report
from db.database import get_conn
from geo.pipeline import create_project, gen_queries, run_probe
from outreach.compose import compose, compose_linkedin_dm
from outreach.enrich import enrich_lead
from outreach.excel import export_xlsx
from outreach.prospect import find_leads
from outreach.send import send_ready


def create_campaign(
    name: str, icp: str, offer: str,
    from_name: str | None = None, from_email: str | None = None, daily_cap: int = 20,
) -> int:
    with get_conn() as conn:
        return conn.execute(
            """
            INSERT INTO campaigns (name, icp, offer, from_name, from_email, daily_cap)
            VALUES (%s, %s, %s, %s, %s, %s) RETURNING id
            """,
            (name, icp, offer, from_name, from_email, daily_cap),
        ).fetchone()["id"]


def _campaign(cid: int) -> dict[str, Any]:
    with get_conn() as conn:
        c = conn.execute("SELECT * FROM campaigns WHERE id = %s", (cid,)).fetchone()
    if not c:
        raise SystemExit(f"no campaign {cid}")
    return c


def run_cycle(
    campaign_id: int, prospect_n: int = 8, geo_queries: int = 6, send: bool = False,
    sync_notion: bool = True,
) -> dict[str, Any]:
    camp = _campaign(campaign_id)
    report(f"outreach: cycle for campaign '{camp['name']}'")

    # 1. prospect (gap-fill) - real web search (Tavily-backed), domain-verified.
    with get_conn() as conn:
        have = {
            r["domain"]
            for r in conn.execute(
                "SELECT domain FROM leads WHERE campaign_id = %s", (campaign_id,)
            ).fetchall()
        }
    found = find_leads(camp["icp"], prospect_n, exclude=have)
    with get_conn() as conn:
        for c in found:
            conn.execute(
                """
                INSERT INTO leads (campaign_id, company, domain, industry, icp_fit, trigger,
                    contact_name, contact_role, linkedin_url, linkedin_activity)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (campaign_id, domain) DO NOTHING
                """,
                (campaign_id, c["company"], c["domain"], c["industry"], c["icp_fit"], c["trigger"],
                 c.get("contact_name"), c.get("contact_role"), c.get("linkedin_url"),
                 c.get("posted_when")),
            )
    report(f"  prospected {len(found)} new companies (from real, recent LinkedIn posts)")

    # 2. enrich (finds the CEO/founder as contact)
    _for_status(campaign_id, "new", lambda lead: _enrich(lead))
    # 3. visibility score (secondary credibility point)
    _for_status(campaign_id, "enriched", lambda lead: _score(lead, camp, geo_queries))
    # 4. draft - both an email sequence AND a LinkedIn message (for manual
    #    sending - LinkedIn retired the internal endpoints this used to rely
    #    on for people search, confirmed via live 410/401 responses, so
    #    there's no automated way to find/message this same person there;
    #    copy the drafted note yourself from the dashboard/Notion instead).
    _for_status(campaign_id, "scored", lambda lead: _draft(lead, camp))

    # 5. mirror every lead + its pitch into Notion (official API, no risk)
    synced = _sync_notion(campaign_id) if sync_notion else 0
    if sync_notion:
        report(f"  synced {synced} leads to Notion")

    # 6. send (optional / SMTP-gated) - email only, LinkedIn stays manual
    sent = send_ready(campaign_id, camp["daily_cap"]) if send else 0
    if send:
        report(f"  sent {sent} first-touch emails")

    path = export_xlsx(campaign_id, "leads.xlsx")
    with get_conn() as conn:
        counts = {
            r["status"]: r["n"]
            for r in conn.execute(
                "SELECT status, COUNT(*) n FROM leads WHERE campaign_id = %s GROUP BY status",
                (campaign_id,),
            ).fetchall()
        }
    report(f"  pipeline: {counts}  ->  {path}")
    return {"found": len(found), "sent": sent, "xlsx": str(path), "pipeline": counts}


def _sync_notion(campaign_id: int) -> int:
    from outreach.notion_sync import sync_lead

    with get_conn() as conn:
        leads = conn.execute(
            "SELECT * FROM leads WHERE campaign_id = %s", (campaign_id,)
        ).fetchall()
    synced = 0
    for lead in leads:
        try:
            with get_conn() as conn:
                m = conn.execute(
                    "SELECT body FROM messages WHERE lead_id = %s AND channel = 'email' "
                    "AND step = 1 ORDER BY id DESC LIMIT 1",
                    (lead["id"],),
                ).fetchone()
                li = conn.execute(
                    "SELECT body FROM messages WHERE lead_id = %s AND channel = 'linkedin' "
                    "AND step = 1 ORDER BY id DESC LIMIT 1",
                    (lead["id"],),
                ).fetchone()
            pitch = m["body"] if m else None
            linkedin_note = li["body"] if li else None
            page_id = sync_lead(dict(lead), pitch=pitch, linkedin_note=linkedin_note)
            if not lead.get("notion_page_id"):
                with get_conn() as conn:
                    conn.execute(
                        "UPDATE leads SET notion_page_id = %s WHERE id = %s",
                        (page_id, lead["id"]),
                    )
            synced += 1
        except Exception as e:  # noqa: BLE001
            report(f"  ! notion sync failed for {lead['company']}: {e}", kind="error")
    return synced


# --------------------------------------------------------------------------- #
def _for_status(campaign_id: int, status: str, fn) -> None:
    while True:
        with get_conn() as conn:
            lead = conn.execute(
                "SELECT * FROM leads WHERE campaign_id = %s AND status = %s "
                "ORDER BY id LIMIT 1",
                (campaign_id, status),
            ).fetchone()
        if not lead:
            return
        try:
            fn(lead)
        except Exception as e:  # noqa: BLE001
            report(f"  ! {lead['company']} ({status}): {e}")
            with get_conn() as conn:
                conn.execute(
                    "UPDATE leads SET status = 'lost', last_action_at = now() WHERE id = %s",
                    (lead["id"],),
                )


def _enrich(lead: dict) -> None:
    e = enrich_lead(lead)
    # prospect.py's contact_name/trigger came from a real, sourced LinkedIn
    # post - keep them over enrich_lead()'s independent (unsourced) guess.
    # Only fill in what prospecting didn't already find.
    contact_name = lead.get("contact_name") or e["contact_name"]
    contact_role = lead.get("contact_role") or e["contact_role"]
    trigger = lead.get("trigger") or e["trigger"]
    with get_conn() as conn:
        conn.execute(
            """
            UPDATE leads SET contact_name = %s, contact_role = %s, contact_email = %s,
                email_status = %s, trigger = %s, status = 'enriched', last_action_at = now()
            WHERE id = %s
            """,
            (contact_name, contact_role, e["contact_email"],
             e["email_status"], trigger, lead["id"]),
        )
    report(f"  enriched {lead['company']} -> {contact_role} <{e['contact_email']}>")


def _score(lead: dict, camp: dict, n: int) -> None:
    pid = create_project(
        f"outreach:{camp['id']}", lead["company"], lead.get("industry") or "software",
        lead["domain"], [],
    )
    gen_queries(pid, n=max(n, 12))
    _run, sc = run_probe(pid, engine="openai", samples=1, limit=n)
    finding = (
        f"appears in {sc['presence_rate']:.0%} of AI answers, avg position "
        f"{sc['avg_position']}, share-of-voice {sc['share_of_voice']:.0%}"
    )
    with get_conn() as conn:
        conn.execute(
            "UPDATE leads SET geo_project_id = %s, geo_score = %s, geo_finding = %s, "
            "status = 'scored', last_action_at = now() WHERE id = %s",
            (pid, sc["score"], finding, lead["id"]),
        )
    report(f"  scored {lead['company']}: {sc['score']}/100")


def _draft(lead: dict, camp: dict) -> None:
    m = compose(lead, camp)
    li = compose_linkedin_dm(lead, camp)
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO messages (lead_id, channel, direction, step, subject, body) "
            "VALUES (%s, 'email', 'out', 1, %s, %s)",
            (lead["id"], m["subject"], m["body"]),
        )
        for step, key in ((2, "followup_1"), (3, "followup_2")):
            conn.execute(
                "INSERT INTO messages (lead_id, channel, direction, step, body) "
                "VALUES (%s, 'email', 'out', %s, %s)",
                (lead["id"], step, m[key]),
            )
        # LinkedIn message - drafted for you to send manually (no working
        # automated way to find/message this person on LinkedIn - see
        # outreach/prospect.py's docstring history / ask about the API breakage).
        conn.execute(
            "INSERT INTO messages (lead_id, channel, direction, step, body) "
            "VALUES (%s, 'linkedin', 'out', 1, %s)",
            (lead["id"], li["note"]),
        )
        conn.execute(
            "INSERT INTO messages (lead_id, channel, direction, step, body) "
            "VALUES (%s, 'linkedin', 'out', 2, %s)",
            (lead["id"], li["followup"]),
        )
        conn.execute(
            "UPDATE leads SET status = 'drafted', last_action_at = now() WHERE id = %s",
            (lead["id"],),
        )
    report(f"  drafted {lead['company']}: \"{m['subject']}\" (+ a LinkedIn note to send yourself)")
