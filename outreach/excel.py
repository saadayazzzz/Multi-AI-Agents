"""Export the whole pipeline to an .xlsx workbook (Leads + Messages sheets)."""
from __future__ import annotations

from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Font

from db.database import get_conn

_LEAD_COLS = [
    "id", "company", "domain", "contact_name", "contact_role", "contact_email",
    "email_status", "industry", "icp_fit", "trigger", "geo_score", "geo_finding",
    "status", "last_action_at", "created_at",
]
_MSG_COLS = ["id", "lead_id", "company", "channel", "direction", "step", "status", "subject", "body", "ts"]


def export_xlsx(campaign_id: int, path: str | Path = "leads.xlsx") -> Path:
    with get_conn() as conn:
        leads = conn.execute(
            f"SELECT {', '.join(_LEAD_COLS)} FROM leads WHERE campaign_id = %s ORDER BY id",
            (campaign_id,),
        ).fetchall()
        msgs = conn.execute(
            """
            SELECT m.id, m.lead_id, l.company, m.channel, m.direction, m.step,
                   m.status, m.subject, m.body, m.ts
            FROM messages m JOIN leads l ON l.id = m.lead_id
            WHERE l.campaign_id = %s ORDER BY m.lead_id, m.id
            """,
            (campaign_id,),
        ).fetchall()

    wb = Workbook()
    ws = wb.active
    ws.title = "Leads"
    ws.append(_LEAD_COLS)
    for r in leads:
        ws.append([_cell(r[c]) for c in _LEAD_COLS])

    ms = wb.create_sheet("Messages")
    ms.append(_MSG_COLS)
    for r in msgs:
        ms.append([_cell(r[c]) for c in _MSG_COLS])

    for sheet in (ws, ms):
        for c in sheet[1]:
            c.font = Font(bold=True)
        sheet.freeze_panes = "A2"

    out = Path(path)
    wb.save(out)
    return out.resolve()


def _cell(v):
    if v is None:
        return ""
    if hasattr(v, "isoformat"):
        return v.isoformat(sep=" ", timespec="minutes")
    return v
