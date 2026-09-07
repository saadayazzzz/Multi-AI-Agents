"""Send drafted first-touch emails over SMTP, rate-limited and cap-respecting.

Enable by setting SMTP_HOST / SMTP_PORT / SMTP_USER / SMTP_PASS and
OUTREACH_FROM_EMAIL (+ optional OUTREACH_FROM_NAME) in .env. Until then this is a
no-op and the drafts just sit in `messages` for manual sending.

Compliance: every body ends with an opt-out line; suppressed addresses are
skipped; keep the daily cap low and use a real, monitored mailbox.
"""
from __future__ import annotations

import os
import smtplib
import time
from email.mime.text import MIMEText

from db.database import get_conn

_HOST = os.getenv("SMTP_HOST")
_PORT = int(os.getenv("SMTP_PORT", "587"))
_USER = os.getenv("SMTP_USER")
_PASS = os.getenv("SMTP_PASS")
_FROM = os.getenv("OUTREACH_FROM_EMAIL")
_FROM_NAME = os.getenv("OUTREACH_FROM_NAME", "")


def smtp_ready() -> bool:
    return all([_HOST, _USER, _PASS, _FROM])


def send_ready(campaign_id: int, cap: int, gap_seconds: float = 20.0) -> int:
    if not smtp_ready():
        print("outreach: SMTP not configured — drafts left for manual sending")
        return 0

    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT m.id AS msg_id, m.subject, m.body, l.id AS lead_id, l.contact_email
            FROM messages m JOIN leads l ON l.id = m.lead_id
            WHERE l.campaign_id = %s AND m.direction = 'out' AND m.step = 1
              AND m.status = 'draft' AND l.status = 'drafted'
              AND l.contact_email IS NOT NULL
              AND l.contact_email NOT IN (SELECT email FROM suppression)
            ORDER BY l.id
            LIMIT %s
            """,
            (campaign_id, cap),
        ).fetchall()

    if not rows:
        return 0

    sent = 0
    with smtplib.SMTP(_HOST, _PORT) as s:
        s.starttls()
        s.login(_USER, _PASS)
        for r in rows:
            msg = MIMEText(r["body"], "plain", "utf-8")
            msg["Subject"] = r["subject"]
            msg["From"] = f"{_FROM_NAME} <{_FROM}>" if _FROM_NAME else _FROM
            msg["To"] = r["contact_email"]
            try:
                s.sendmail(_FROM, [r["contact_email"]], msg.as_string())
            except Exception as e:  # noqa: BLE001
                print(f"  send failed {r['contact_email']}: {e}")
                continue
            with get_conn() as conn:
                conn.execute("UPDATE messages SET status = 'sent', ts = now() WHERE id = %s", (r["msg_id"],))
                conn.execute(
                    "UPDATE leads SET status = 'sent', last_action_at = now() WHERE id = %s",
                    (r["lead_id"],),
                )
            sent += 1
            print(f"  sent -> {r['contact_email']}")
            time.sleep(gap_seconds)
    return sent
