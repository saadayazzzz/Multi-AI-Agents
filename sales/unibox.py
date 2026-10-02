"""Unibox: every LinkedIn + email conversation in one inbox.

Inbound messages from known contacts mark their sequence step 'answered'
(Gojiberry's reply definition) and stop every remaining step for that
contact - nobody gets a follow-up after they've replied.
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any

from db.database import get_conn
from sales import linkedin as li

# ---------------------------------------------------------------- threads --


def _thread(channel: str, seat_id: int | None, external_id: str, **fields: Any) -> int:
    with get_conn() as conn:
        r = conn.execute(
            "SELECT id FROM sales_threads WHERE channel = %s AND seat_id IS NOT DISTINCT FROM %s AND external_id = %s",
            (channel, seat_id, external_id),
        ).fetchone()
        if r:
            sets = [(k, v) for k, v in fields.items() if v is not None]
            if sets:
                conn.execute(
                    f"UPDATE sales_threads SET {', '.join(f'{k} = COALESCE({k}, %s)' for k, _ in sets)} WHERE id = %s",
                    (*[v for _, v in sets], r["id"]),
                )
            return r["id"]
        cols = ["channel", "seat_id", "external_id"] + [k for k, v in fields.items() if v is not None]
        vals = [channel, seat_id, external_id] + [v for v in fields.values() if v is not None]
        return conn.execute(
            f"INSERT INTO sales_threads ({', '.join(cols)}) VALUES ({', '.join(['%s'] * len(cols))}) RETURNING id",
            vals,
        ).fetchone()["id"]


def _find_contact(email_addr: str | None, profile_url: str | None) -> dict | None:
    with get_conn() as conn:
        if profile_url:
            r = conn.execute("SELECT * FROM sales_contacts WHERE profile_url = %s",
                             (profile_url.split("?")[0].rstrip("/"),)).fetchone()
            if r:
                return r
        if email_addr:
            return conn.execute("SELECT * FROM sales_contacts WHERE lower(email) = lower(%s) LIMIT 1",
                                (email_addr,)).fetchone()
    return None


def _add_message(thread_id: int, direction: str, sender: str | None, body: str, sent_at: datetime,
                 external_id: str | None, status: str, attachment: dict | None = None) -> bool:
    from sales.db import jsonb

    ext = external_id or hashlib.sha1(f"{direction}|{sender}|{body}".encode()).hexdigest()
    with get_conn() as conn:
        r = conn.execute(
            "INSERT INTO sales_thread_messages (thread_id, direction, sender, body, sent_at, external_id, status, attachment) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s) ON CONFLICT (thread_id, external_id) DO NOTHING RETURNING id",
            (thread_id, direction, sender, body, sent_at, ext, status, jsonb(attachment) if attachment else None),
        ).fetchone()
        if r:
            conn.execute(
                "UPDATE sales_threads SET last_message_at = GREATEST(COALESCE(last_message_at, %s), %s), "
                "last_message_preview = %s, seen = CASE WHEN %s = 'in' THEN false ELSE seen END WHERE id = %s",
                (sent_at, sent_at, body[:200], direction, thread_id),
            )
    return r is not None


def mark_answered(contact_id: int, channel: str) -> None:
    types = ("email",) if channel == "email" else ("message", "voiceMessage")
    with get_conn() as conn:
        last = conn.execute(
            "SELECT id FROM sales_campaign_status WHERE contact_id = %s AND type = ANY(%s) "
            "AND state IN ('sent', 'delivered') ORDER BY done_at DESC NULLS LAST LIMIT 1",
            (contact_id, list(types)),
        ).fetchone()
        if not last:  # replied on the other channel than the last touch
            last = conn.execute(
                "SELECT id FROM sales_campaign_status WHERE contact_id = %s "
                "AND type IN ('message', 'voiceMessage', 'email') AND state IN ('sent', 'delivered') "
                "ORDER BY done_at DESC NULLS LAST LIMIT 1",
                (contact_id,),
            ).fetchone()
        if last:
            conn.execute("UPDATE sales_campaign_status SET state = 'answered', updated_at = now() WHERE id = %s",
                         (last["id"],))
        conn.execute(
            "UPDATE sales_campaign_status SET state = 'skipped', error = 'contact replied', updated_at = now() "
            "WHERE contact_id = %s AND state IN ('waiting', 'pending', 'manual')",
            (contact_id,),
        )


def _rekey(seat_id: int | None, profile_url: str, thread_url: str) -> None:
    """Campaign DMs are filed under the contact's profile URL until we learn
    LinkedIn's real thread URL - then the thread is re-keyed so the
    conversation stays one thread."""
    old = profile_url.split("?")[0].rstrip("/")
    if old == thread_url:
        return
    with get_conn() as conn:
        conn.execute(
            "UPDATE sales_threads SET external_id = %s WHERE channel = 'linkedin' "
            "AND seat_id IS NOT DISTINCT FROM %s AND external_id = %s AND NOT EXISTS ("
            "SELECT 1 FROM sales_threads WHERE channel = 'linkedin' AND seat_id IS NOT DISTINCT FROM %s "
            "AND external_id = %s)",
            (thread_url, seat_id, old, seat_id, thread_url),
        )


def record_inbound(*, channel: str, seat_id: int | None, external_thread_id: str, sender: str | None,
                   body: str, sent_at: datetime, external_message_id: str | None,
                   attendee_name: str | None = None, attendee_email: str | None = None,
                   attendee_profile_url: str | None = None, subject: str | None = None,
                   only_known_contacts: bool = False) -> bool:
    contact = _find_contact(attendee_email, attendee_profile_url)
    if only_known_contacts and not contact:
        return False
    if channel == "linkedin" and contact and contact.get("profile_url"):
        _rekey(seat_id, contact["profile_url"], external_thread_id)
    tid = _thread(
        channel, seat_id, external_thread_id, contact_id=contact["id"] if contact else None,
        attendee_full_name=attendee_name or (contact or {}).get("full_name"),
        attendee_profile_url=attendee_profile_url, attendee_email=attendee_email, subject=subject,
    )
    new = _add_message(tid, "in", sender, body, sent_at, external_message_id, "received")
    if new and contact:
        mark_answered(contact["id"], channel)
        _classify(tid, body)
    return new


def record_outbound(*, channel: str, seat_id: int | None, contact: dict, body: str,
                    external_message_id: str | None = None, subject: str | None = None,
                    sender: str | None = None, thread_external_id: str | None = None) -> int:
    ext = thread_external_id or (
        (contact.get("email") or "").lower() if channel == "email" else contact.get("profile_url") or str(contact["id"])
    )
    tid = _thread(channel, seat_id, ext, contact_id=contact["id"], attendee_full_name=contact.get("full_name"),
                  attendee_profile_url=contact.get("profile_url"), attendee_email=contact.get("email"),
                  subject=subject)
    _add_message(tid, "out", sender, body, datetime.now(timezone.utc), external_message_id, "sent")
    return tid


# ----------------------------------------------------------- classification --

_SCHEMA = {
    "type": "object",
    "properties": {"interested": {"type": ["boolean", "null"]}},
    "required": ["interested"],
    "additionalProperties": False,
}


def _classify(thread_id: int, body: str) -> None:
    """true = wants to talk / asks for info, false = no / unsubscribe /
    out-of-office, null = can't tell."""
    try:
        from agents.llm import json_out

        r = json_out(
            "Classify a reply to a cold outreach message. interested=true if they want to talk, "
            "ask a question, or ask for details; false if it's a no, an unsubscribe request, or "
            "an auto-reply; null if unclear.",
            body[:2000], _SCHEMA, max_tokens=50,
        )
        val = r.get("interested")
    except Exception:  # noqa: BLE001 - classification is a nice-to-have
        low = body.lower()
        val = False if any(w in low for w in ("unsubscribe", "not interested", "remove me", "out of office")) else None
    with get_conn() as conn:
        conn.execute("UPDATE sales_threads SET interested = %s WHERE id = %s", (val, thread_id))


# ------------------------------------------------------------------ reads --

def list_threads(*, seat_id: int | None = None, channel: str | None = None, attendee_full_name: str | None = None,
                 date_from: str | None = None, date_to: str | None = None, interested: bool | None = None,
                 seen: bool | None = None, page: int = 1, limit: int = 20, order: str = "DESC") -> dict:
    where, vals = ["true"], []
    for col, v in (("seat_id", seat_id), ("channel", channel), ("interested", interested), ("seen", seen)):
        if v is not None:
            where.append(f"{col} = %s")
            vals.append(v)
    if attendee_full_name:
        where.append("attendee_full_name ILIKE %s")
        vals.append(f"%{attendee_full_name}%")
    if date_from:
        where.append("last_message_at >= %s::timestamptz")
        vals.append(date_from)
    if date_to:
        where.append("last_message_at <= %s::timestamptz")
        vals.append(date_to)
    order = "ASC" if str(order).upper() == "ASC" else "DESC"
    limit = max(1, min(int(limit), 100))
    page = max(1, int(page))
    w = " AND ".join(where)
    with get_conn() as conn:
        total = conn.execute(f"SELECT COUNT(*) n FROM sales_threads WHERE {w}", vals).fetchone()["n"]
        items = conn.execute(
            f"SELECT * FROM sales_threads WHERE {w} ORDER BY last_message_at {order} NULLS LAST, id DESC "
            f"LIMIT %s OFFSET %s",
            (*vals, limit, (page - 1) * limit),
        ).fetchall()
    return {"items": items, "total": total, "page": page, "limit": limit}


def thread_messages(thread_id: int) -> list[dict]:
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM sales_thread_messages WHERE thread_id = %s ORDER BY sent_at, id", (thread_id,)
        ).fetchall()


def threads_for_contact(contact_id: int) -> list[dict]:
    with get_conn() as conn:
        return conn.execute("SELECT * FROM sales_threads WHERE contact_id = %s ORDER BY last_message_at DESC",
                            (contact_id,)).fetchall()


def update_thread(thread_id: int, *, seen: bool | None = None, interested: bool | None = None) -> None:
    with get_conn() as conn:
        if seen is not None:
            conn.execute("UPDATE sales_threads SET seen = %s WHERE id = %s", (seen, thread_id))
        if interested is not None:
            conn.execute("UPDATE sales_threads SET interested = %s WHERE id = %s", (interested, thread_id))


# ------------------------------------------------------------------ write --

def send_message(thread_id: int, message: str, attachment: dict | None = None) -> dict:
    """Reply from the unibox. The user typed this themselves, so it goes out
    even with campaign automation off (it's their own message, sent once)."""
    from sales import emailer

    with get_conn() as conn:
        t = conn.execute("SELECT * FROM sales_threads WHERE id = %s", (thread_id,)).fetchone()
    if not t:
        raise ValueError(f"thread {thread_id} not found")
    if t["channel"] == "linkedin":
        seat = li.get_seat(t["seat_id"]) or li.default_seat()
        li.call("reply", {"thread_url": t["external_id"], "text": message, "file": (attachment or {}).get("path")},
                seat, user_initiated=True)
        _add_message(thread_id, "out", (seat or {}).get("name"), message, datetime.now(timezone.utc), None, "sent",
                     attachment)
    else:
        seat = emailer.get_seat(t["seat_id"])
        if not seat:
            raise ValueError("this thread's email seat no longer exists")
        with get_conn() as conn:
            last_in = conn.execute(
                "SELECT external_id FROM sales_thread_messages WHERE thread_id = %s AND direction = 'in' "
                "ORDER BY sent_at DESC LIMIT 1", (thread_id,),
            ).fetchone()
        subj = t.get("subject") or ""
        subj = subj if subj.lower().startswith("re:") else f"Re: {subj}".strip()
        mid = emailer.send(seat, t["attendee_email"], subj, message,
                           in_reply_to=(last_in or {}).get("external_id"))
        _add_message(thread_id, "out", seat["email"], message, datetime.now(timezone.utc), mid, "sent")
    update_thread(thread_id, seen=True)
    return {"status": "sent", "thread_id": thread_id}


# ------------------------------------------------------------- LinkedIn sync --

def sync_linkedin(seat: dict, max_threads: int = 20) -> dict[str, int]:
    stats = {"threads": 0, "new_messages": 0}
    threads = li.call("inbox", {"max": max_threads}, seat) or []
    me = (seat.get("name") or "").strip().lower()
    for th in threads:
        with get_conn() as conn:
            known = conn.execute(
                "SELECT last_message_preview FROM sales_threads WHERE channel = 'linkedin' AND seat_id = %s "
                "AND external_id = %s", (seat["id"], th["thread_url"]),
            ).fetchone()
        if known and not th.get("unread") and (known["last_message_preview"] or "")[:60] == (th.get("preview") or "")[:60]:
            continue
        stats["threads"] += 1
        data = li.call("thread", {"url": th["thread_url"], "max": 30}, seat) or {}
        me_name = (data.get("me") or me or "").strip().lower()
        other_url = next((m.get("sender_url") for m in data.get("messages", [])
                          if m.get("sender_url") and (m.get("sender") or "").strip().lower() != me_name), None)
        if other_url:
            _rekey(seat["id"], other_url, th["thread_url"])
        for m in data.get("messages", []):
            mine = me_name and (m.get("sender") or "").strip().lower() == me_name
            ext = m.get("id") or hashlib.sha1(f"{m.get('sender')}|{m.get('time')}|{m.get('body')}".encode()).hexdigest()
            if mine:
                contact = _find_contact(None, other_url)
                if contact:
                    tid = _thread("linkedin", seat["id"], th["thread_url"], contact_id=contact["id"],
                                  attendee_full_name=th.get("attendee_full_name"), attendee_profile_url=other_url)
                    stats["new_messages"] += _add_message(tid, "out", m.get("sender"), m["body"],
                                                          datetime.now(timezone.utc), ext, "sent")
                continue
            stats["new_messages"] += record_inbound(
                channel="linkedin", seat_id=seat["id"], external_thread_id=th["thread_url"],
                sender=m.get("sender"), body=m["body"], sent_at=datetime.now(timezone.utc),
                external_message_id=ext, attendee_name=th.get("attendee_full_name"),
                attendee_profile_url=other_url,
            )
    return stats
