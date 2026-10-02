"""Email seats: sending with caps + warm-up ramp, open tracking, unsubscribe,
and IMAP reply / bounce sync into the unibox.

A seat is any mailbox reachable over SMTP (+ IMAP for replies). 'google'
and 'outlook' seats just preset the hosts - use an app password. Real
warm-up networks (mailboxes exchanging mail to build reputation) need a pool
of other senders; what this does is the half that matters most for a single
sender: a slow daily-volume ramp until the seat reaches its daily max.
"""
from __future__ import annotations

import email
import email.utils
import imaplib
import os
import re
import secrets
import smtplib
from datetime import date, datetime, timezone
from email.header import decode_header, make_header
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from html import escape
from typing import Any

from config import settings
from db.database import get_conn
from sales.linkedin import take_quota, used_today

PRESETS = {
    "google": {"smtp_host": "smtp.gmail.com", "smtp_port": 587, "imap_host": "imap.gmail.com", "imap_port": 993},
    "outlook": {"smtp_host": "smtp.office365.com", "smtp_port": 587, "imap_host": "outlook.office365.com", "imap_port": 993},
}

_FIELDS = [
    "email", "name", "first_name", "last_name", "type", "smtp_host", "smtp_port", "smtp_user",
    "smtp_pass", "imap_host", "imap_port", "daily_email_max", "launch_hour", "active_days",
    "timezone", "track_opening", "remove_unsubscribe_link", "warmup_enabled", "signature",
]


def _public(seat: dict | None) -> dict | None:
    if seat is None:
        return None
    s = {k: v for k, v in seat.items() if k != "smtp_pass"}
    s["has_password"] = bool(seat.get("smtp_pass"))
    s["daily_email_count"] = used_today("email", seat["id"], "email")
    s["daily_cap_today"] = warmup_cap(seat)
    return s


def create_seat(**fields: Any) -> dict:
    t = fields.get("type") or "smtp"
    for k, v in PRESETS.get(t, {}).items():
        fields.setdefault(k, v)
    fields.setdefault("smtp_user", fields.get("email"))
    cols = [c for c in _FIELDS if fields.get(c) is not None]
    with get_conn() as conn:
        row = conn.execute(
            f"INSERT INTO email_seats ({', '.join(cols)}, warmup_started_at) "
            f"VALUES ({', '.join(['%s'] * len(cols))}, now()) RETURNING *",
            [fields[c] for c in cols],
        ).fetchone()
    return _public(row)


def update_seat(seat_id: int, **fields: Any) -> dict | None:
    sets = [(c, v) for c, v in fields.items() if c in _FIELDS and v is not None]
    if sets:
        with get_conn() as conn:
            conn.execute(
                f"UPDATE email_seats SET {', '.join(f'{c} = %s' for c, _ in sets)} WHERE id = %s",
                (*[v for _, v in sets], seat_id),
            )
    return _public(get_seat(seat_id))


def get_seat(seat_id: int) -> dict | None:
    with get_conn() as conn:
        return conn.execute("SELECT * FROM email_seats WHERE id = %s", (seat_id,)).fetchone()


def list_seats() -> list[dict]:
    with get_conn() as conn:
        return [_public(r) for r in conn.execute("SELECT * FROM email_seats ORDER BY id").fetchall()]


def delete_seat(seat_id: int) -> None:
    with get_conn() as conn:
        conn.execute("DELETE FROM email_seats WHERE id = %s", (seat_id,))


def seat_from_env() -> dict | None:
    """Turn the legacy SMTP_* settings (outreach/send.py) into a seat, once."""
    addr = os.getenv("OUTREACH_FROM_EMAIL")
    if not (addr and os.getenv("SMTP_HOST")):
        return None
    with get_conn() as conn:
        if conn.execute("SELECT 1 FROM email_seats WHERE email = %s", (addr,)).fetchone():
            return None
    return create_seat(
        email=addr, name=os.getenv("OUTREACH_FROM_NAME") or None, smtp_host=os.getenv("SMTP_HOST"),
        smtp_port=int(os.getenv("SMTP_PORT", "587")), smtp_user=os.getenv("SMTP_USER"),
        smtp_pass=os.getenv("SMTP_PASS"), imap_host=os.getenv("IMAP_HOST"),
    )


# ---------------------------------------------------------------- warm-up --

def warmup_cap(seat: dict, today: date | None = None) -> int:
    """5/day on day one, +3/day after, until daily_email_max."""
    mx = int(seat.get("daily_email_max") or 30)
    if not seat.get("warmup_enabled") or seat.get("warmup_completed"):
        return mx
    start = seat.get("warmup_started_at")
    if not start:
        return min(mx, 5)
    days = ((today or date.today()) - start.date()).days
    cap = min(mx, 5 + 3 * max(0, days))
    if cap >= mx:
        with get_conn() as conn:
            conn.execute("UPDATE email_seats SET warmup_completed = true WHERE id = %s", (seat["id"],))
    return cap


def take_email_quota(seat: dict) -> bool:
    return take_quota("email", seat["id"], "email", warmup_cap(seat))


# ---------------------------------------------------------------- sending --

def _base_url() -> str:
    return settings.public_base_url or f"http://{settings.server_host}:{settings.server_port}"


def _html(body: str, pixel: str | None, unsub: str | None, signature: str | None) -> str:
    paras = "".join(f"<p>{escape(p).replace(chr(10), '<br>')}</p>" for p in body.split("\n\n"))
    if signature:
        paras += f"<p>{escape(signature).replace(chr(10), '<br>')}</p>"
    if unsub:
        paras += f'<p style="font-size:12px;color:#888">Not relevant? <a href="{unsub}">Unsubscribe</a></p>'
    if pixel:
        paras += f'<img src="{pixel}" width="1" height="1" alt="" style="display:none">'
    return f"<div>{paras}</div>"


def build_message(seat: dict, to: str, subject: str, body: str, token: str,
                  in_reply_to: str | None = None) -> tuple[MIMEMultipart, str]:
    base = _base_url()
    unsub = None if seat.get("remove_unsubscribe_link") else f"{base}/api/sales/t/u/{token}"
    pixel = f"{base}/api/sales/t/o/{token}.gif" if seat.get("track_opening") else None
    text = body + (f"\n\n{seat['signature']}" if seat.get("signature") else "")
    if unsub:
        text += f"\n\nNot relevant? Unsubscribe: {unsub}"
    msg = MIMEMultipart("alternative")
    msg.attach(MIMEText(text, "plain", "utf-8"))
    msg.attach(MIMEText(_html(body, pixel, unsub, seat.get("signature")), "html", "utf-8"))
    domain = seat["email"].split("@")[-1]
    mid = email.utils.make_msgid(domain=domain)
    msg["Message-ID"] = mid
    msg["Subject"] = subject
    msg["From"] = email.utils.formataddr((seat.get("name") or "", seat["email"]))
    msg["To"] = to
    msg["Date"] = email.utils.formatdate(localtime=True)
    if in_reply_to:
        msg["In-Reply-To"] = in_reply_to
        msg["References"] = in_reply_to
    if unsub:
        msg["List-Unsubscribe"] = f"<{unsub}>"
        msg["List-Unsubscribe-Post"] = "List-Unsubscribe=One-Click"
    return msg, mid


def send(seat: dict, to: str, subject: str, body: str, *, status_id: int | None = None,
         in_reply_to: str | None = None) -> str:
    """Send one email. Returns its Message-ID. Raises on SMTP failure."""
    token = secrets.token_urlsafe(16)
    msg, mid = build_message(seat, to, subject, body, token, in_reply_to)
    with smtplib.SMTP(seat["smtp_host"], int(seat["smtp_port"]), timeout=30) as s:
        s.starttls()
        s.login(seat.get("smtp_user") or seat["email"], seat["smtp_pass"])
        s.sendmail(seat["email"], [to], msg.as_string())
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO sales_email_events (token, status_id, kind) VALUES (%s, %s, 'sent')",
            (token, status_id),
        )
    return mid


# --------------------------------------------------------------- tracking --

def record_open(token: str) -> None:
    with get_conn() as conn:
        r = conn.execute("SELECT status_id FROM sales_email_events WHERE token = %s AND kind = 'sent'", (token,)).fetchone()
        if r:
            conn.execute("INSERT INTO sales_email_events (token, status_id, kind) VALUES (%s, %s, 'open')",
                         (token, r["status_id"]))


def unsubscribe(token: str) -> bool:
    with get_conn() as conn:
        r = conn.execute(
            "SELECT e.status_id, s.contact_id, c.email FROM sales_email_events e "
            "JOIN sales_campaign_status s ON s.id = e.status_id JOIN sales_contacts c ON c.id = s.contact_id "
            "WHERE e.token = %s AND e.kind = 'sent'",
            (token,),
        ).fetchone()
        if not r:
            return False
        conn.execute("INSERT INTO sales_email_events (token, status_id, kind) VALUES (%s, %s, 'unsubscribe')",
                     (token, r["status_id"]))
        conn.execute("UPDATE sales_contacts SET unsubscribed = true WHERE id = %s", (r["contact_id"],))
        if r["email"]:
            conn.execute("INSERT INTO suppression (email, reason) VALUES (lower(%s), 'unsubscribe') "
                         "ON CONFLICT (email) DO NOTHING", (r["email"],))
        conn.execute(
            "UPDATE sales_campaign_status SET state = 'skipped', error = 'unsubscribed', updated_at = now() "
            "WHERE contact_id = %s AND state IN ('waiting', 'pending', 'manual')",
            (r["contact_id"],),
        )
    return True


def is_suppressed(addr: str) -> bool:
    with get_conn() as conn:
        return bool(conn.execute("SELECT 1 FROM suppression WHERE lower(email) = lower(%s)", (addr,)).fetchone())


# ------------------------------------------------------------- IMAP sync --

def _dec(v: str | None) -> str:
    if not v:
        return ""
    try:
        return str(make_header(decode_header(v)))
    except Exception:  # noqa: BLE001
        return v


def _text_body(msg: email.message.Message) -> str:
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/plain" and "attachment" not in str(part.get("Content-Disposition")):
                return (part.get_payload(decode=True) or b"").decode(part.get_content_charset() or "utf-8", "replace")
        for part in msg.walk():
            if part.get_content_type() == "text/html":
                html = (part.get_payload(decode=True) or b"").decode(part.get_content_charset() or "utf-8", "replace")
                return re.sub(r"<[^>]+>", " ", html)
        return ""
    return (msg.get_payload(decode=True) or b"").decode(msg.get_content_charset() or "utf-8", "replace")


def strip_quoted(body: str) -> str:
    """Keep only the new text of a reply."""
    lines = []
    for line in body.splitlines():
        if line.startswith(">") or re.match(r"^On .+wrote:$", line.strip()) or line.strip() == "-- ":
            break
        lines.append(line)
    return "\n".join(lines).strip()


_BOUNCE_FROM = re.compile(r"mailer-daemon|postmaster", re.I)
_ADDR = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")


def sync_inbox(seat: dict, limit: int = 200) -> dict[str, int]:
    """Pull new mail since the last seen UID; replies from known contacts land
    in the unibox (and stop their sequences), bounces mark the address."""
    from sales.unibox import record_inbound

    if not seat.get("imap_host") or not seat.get("smtp_pass"):
        return {"skipped": 1}
    stats = {"replies": 0, "bounces": 0, "ignored": 0}
    m = imaplib.IMAP4_SSL(seat["imap_host"], int(seat.get("imap_port") or 993))
    try:
        m.login(seat.get("smtp_user") or seat["email"], seat["smtp_pass"])
        m.select("INBOX", readonly=True)
        last = int(seat.get("last_imap_uid") or 0)
        if last:
            typ, data = m.uid("search", None, f"UID {last + 1}:*")
        else:
            since = datetime.now(timezone.utc).strftime("%d-%b-%Y")
            typ, data = m.uid("search", None, f"SINCE {since}")
        uids = [int(u) for u in (data[0] or b"").split() if int(u) > last][-limit:]
        for uid in uids:
            typ, msgdata = m.uid("fetch", str(uid), "(RFC822)")
            if not msgdata or not msgdata[0]:
                continue
            msg = email.message_from_bytes(msgdata[0][1])
            frm = email.utils.parseaddr(_dec(msg.get("From")))[1].lower()
            body = _text_body(msg)
            if _BOUNCE_FROM.search(frm):
                for addr in set(_ADDR.findall(body)):
                    with get_conn() as conn:
                        n = conn.execute(
                            "UPDATE sales_contacts SET email_status = 'bounced' WHERE lower(email) = lower(%s)",
                            (addr,),
                        ).rowcount
                    stats["bounces"] += n
                continue
            sent_at = email.utils.parsedate_to_datetime(msg["Date"]) if msg.get("Date") else datetime.now(timezone.utc)
            ok = record_inbound(
                channel="email", seat_id=seat["id"], external_thread_id=frm, sender=frm,
                attendee_email=frm, attendee_name=email.utils.parseaddr(_dec(msg.get("From")))[0] or None,
                body=strip_quoted(body), sent_at=sent_at, external_message_id=msg.get("Message-ID") or f"uid:{uid}",
                subject=_dec(msg.get("Subject")), only_known_contacts=True,
            )
            stats["replies" if ok else "ignored"] += 1
        if uids:
            with get_conn() as conn:
                conn.execute("UPDATE email_seats SET last_imap_uid = %s WHERE id = %s", (max(uids), seat["id"]))
    finally:
        try:
            m.logout()
        except Exception:  # noqa: BLE001
            pass
    return stats
