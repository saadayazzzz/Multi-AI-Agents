"""Campaign executor: walks every contact through its campaign's steps.

Each contact x campaign x step is one sales_campaign_status row
(Gojiberry's contact.campaignStatus). States:

  waiting  - an earlier step hasn't happened yet
  pending  - due at due_at; the next tick runs it
  manual   - due, drafted, waiting for the user to do it by hand
             (manual campaigns, or LinkedIn automation off on the seat)
  sent / delivered / accepted / answered / skipped / failed

A tick (sales/scheduler.py calls it every few minutes) only does work on the
campaign's active days, from its launch hour on, and inside every seat's
daily caps. A reply on any channel stops the contact's remaining steps
(sales/unibox.py). LinkedIn DMs wait for the invitation to be accepted; after
skip_invitation_after_days without acceptance they're skipped and only the
email steps continue - Gojiberry's own skipInvitationAfterDays behaviour.
"""
from __future__ import annotations

import contextlib
from datetime import datetime, timedelta, timezone
from typing import Any, Iterator
from zoneinfo import ZoneInfo

import psycopg

from agents.reporter import report
from config import settings
from db.database import get_conn
from sales import emailer
from sales import linkedin as li
from sales.campaigns import get_campaign
from sales.constants import INVITATION_STEPS, INVITE_NOTE_MAX, INVITE_NOTE_MAX_SALES_NAV, LINKEDIN_STEPS
from sales.writer import content_for, split_paragraphs

MAX_ATTEMPTS = 3
DEFAULT_DAYS = [1, 2, 3, 4, 5]


class QuotaReached(Exception):
    pass


# --------------------------------------------------------------- schedule --

def _tz(campaign: dict, seat: dict | None) -> ZoneInfo:
    try:
        return ZoneInfo((seat or {}).get("timezone") or "UTC")
    except Exception:  # noqa: BLE001
        return ZoneInfo("UTC")


def _days(campaign: dict, seat: dict | None) -> list[int]:
    return list(campaign.get("active_days") or (seat or {}).get("active_days") or DEFAULT_DAYS)


def schedule_after(start: datetime, delay_days: int, active_days: list[int], launch_hour: int,
                   tz: ZoneInfo) -> datetime:
    """`delay_days` calendar days later, at the launch hour, rolled forward
    to the next active weekday."""
    local = start.astimezone(tz) + timedelta(days=delay_days)
    local = local.replace(hour=launch_hour, minute=0, second=0, microsecond=0)
    for _ in range(8):
        if local.isoweekday() in active_days:
            break
        local += timedelta(days=1)
    return local.astimezone(timezone.utc)


def in_window(campaign: dict, seat: dict | None, now: datetime) -> bool:
    local = now.astimezone(_tz(campaign, seat))
    return local.isoweekday() in _days(campaign, seat) and local.hour >= int(campaign.get("launch_hour") or 9)


# -------------------------------------------------------------- enrolment --

def enroll(campaign: dict, now: datetime) -> int:
    steps = campaign["steps"] or []
    if not steps:
        return 0
    with get_conn() as conn:
        contacts = conn.execute(
            """
            SELECT DISTINCT c.id, c.connection_degree FROM sales_contacts c
            JOIN sales_list_contacts lc ON lc.contact_id = c.id
            JOIN sales_lists l ON l.id = lc.list_id
            WHERE l.campaign_agent_id = %s AND NOT c.rejected AND NOT c.unsubscribed
              AND NOT EXISTS (SELECT 1 FROM sales_campaign_status s
                              WHERE s.contact_id = c.id AND s.campaign_agent_id = %s)
            """,
            (campaign["id"], campaign["id"]),
        ).fetchall()
        n = 0
        for c in contacts:
            if campaign.get("exclude_first_degree") and c["connection_degree"] == 1:
                continue
            for s in steps:
                conn.execute(
                    """INSERT INTO sales_campaign_status
                       (contact_id, campaign_agent_id, step_id, step_number, type, state, due_at)
                       VALUES (%s, %s, %s, %s, %s, %s, %s) ON CONFLICT DO NOTHING""",
                    (c["id"], campaign["id"], s["id"], s["step_number"], s["type"],
                     "pending" if s["step_number"] == 0 else "waiting",
                     now if s["step_number"] == 0 else None),
                )
            n += 1
    return n


# ------------------------------------------------------------- transitions --

def _set(status_id: int, **fields: Any) -> None:
    cols = ", ".join(f"{k} = %s" for k in fields)
    with get_conn() as conn:
        conn.execute(f"UPDATE sales_campaign_status SET {cols}, updated_at = now() WHERE id = %s",
                     (*fields.values(), status_id))


def _advance(row: dict, campaign: dict, seat: dict | None, now: datetime) -> None:
    """Make the next step pending, `delay_after_last_step` days from now."""
    steps = campaign["steps"]
    nxt = next((s for s in steps if s["step_number"] == row["step_number"] + 1), None)
    if not nxt:
        return
    due = schedule_after(now, int(nxt.get("delay_after_last_step") or 2), _days(campaign, seat),
                         int(campaign.get("launch_hour") or 9), _tz(campaign, seat))
    with get_conn() as conn:
        conn.execute(
            "UPDATE sales_campaign_status SET state = 'pending', due_at = %s, updated_at = now() "
            "WHERE contact_id = %s AND campaign_agent_id = %s AND step_number = %s AND state = 'waiting'",
            (due, row["contact_id"], row["campaign_agent_id"], nxt["step_number"]),
        )


def finish(row: dict, campaign: dict, seat: dict | None, now: datetime, state: str, **extra: Any) -> None:
    _set(row["id"], state=state, done_at=now, **extra)
    _advance(row, campaign, seat, now)


def complete_manual(status_id: int, outcome: str = "sent", now: datetime | None = None) -> dict:
    """The user did a manual step by hand (or decided to skip it)."""
    if outcome not in ("sent", "skipped", "accepted"):
        raise ValueError("outcome must be sent, skipped or accepted")
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM sales_campaign_status WHERE id = %s", (status_id,)).fetchone()
    if not row or row["state"] != "manual":
        raise ValueError(f"status {status_id} isn't an open manual task")
    campaign = get_campaign(row["campaign_agent_id"])
    seat = li.get_seat(campaign.get("linkedin_seat_id"))
    now = now or datetime.now(timezone.utc)
    finish(row, campaign, seat, now, outcome)
    if outcome == "sent" and row["type"] in ("message", "invitationNote") and row.get("body"):
        from sales.unibox import record_outbound

        with get_conn() as conn:
            contact = conn.execute("SELECT * FROM sales_contacts WHERE id = %s", (row["contact_id"],)).fetchone()
        record_outbound(channel="linkedin", seat_id=campaign.get("linkedin_seat_id"), contact=contact,
                        body=row["body"], sender=(seat or {}).get("name"))
    return {"status_id": status_id, "state": outcome}


def manual_tasks(campaign_id: int | None = None, limit: int = 100) -> list[dict]:
    where, vals = ["s.state = 'manual'"], []
    if campaign_id:
        where.append("s.campaign_agent_id = %s")
        vals.append(campaign_id)
    with get_conn() as conn:
        return conn.execute(
            f"""SELECT s.*, c.full_name, c.profile_url, c.email, c.company, c.job_title, ca.name AS campaign_name
                FROM sales_campaign_status s JOIN sales_contacts c ON c.id = s.contact_id
                JOIN campaign_agents ca ON ca.id = s.campaign_agent_id
                WHERE {' AND '.join(where)} ORDER BY s.due_at LIMIT %s""",
            (*vals, limit),
        ).fetchall()


# --------------------------------------------------------------- execution --

def _prior(row: dict) -> list[dict]:
    with get_conn() as conn:
        return conn.execute(
            "SELECT step_number, type, body FROM sales_campaign_status WHERE contact_id = %s "
            "AND campaign_agent_id = %s AND step_number < %s AND body IS NOT NULL ORDER BY step_number",
            (row["contact_id"], row["campaign_agent_id"], row["step_number"]),
        ).fetchall()


def _invite_row(row: dict) -> dict | None:
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM sales_campaign_status WHERE contact_id = %s AND campaign_agent_id = %s "
            "AND type IN ('invitation', 'invitationNote')",
            (row["contact_id"], row["campaign_agent_id"]),
        ).fetchone()


def _automated(campaign: dict, seat: dict | None) -> bool:
    return bool(not campaign.get("is_manual") and seat and seat.get("automation_enabled") and li.has_session(seat))


def _quota(seat: dict, action: str) -> None:
    if not li.take_quota("linkedin", seat["id"], action, li.seat_cap(seat, action)):
        raise QuotaReached(action)


def _linkedin_gate(row: dict, campaign: dict, contact: dict, now: datetime, can_detect: bool) -> str:
    """For DM steps: 'ok', 'wait' (invitation still pending) or 'skip'.
    Without a session we can't see acceptances, so the manual task is
    handed to the user, who can see it themselves."""
    if contact.get("connection_degree") == 1 or not can_detect:
        return "ok"
    inv = _invite_row(row)
    if not inv:
        return "ok"  # no invitation in the sequence - try; LinkedIn says if not connected
    if inv["state"] == "accepted":
        return "ok"
    if inv["state"] in ("skipped", "failed"):
        return "skip"
    sent_at = inv.get("done_at")
    if sent_at and now - sent_at > timedelta(days=int(campaign.get("skip_invitation_after_days") or 7)):
        return "skip"
    return "wait"


def execute(row: dict, campaign: dict, seat: dict | None, now: datetime) -> str:
    """Run one due step. Returns the resulting state."""
    with get_conn() as conn:
        contact = conn.execute("SELECT * FROM sales_contacts WHERE id = %s", (row["contact_id"],)).fetchone()
    step = next((s for s in campaign["steps"] if s["step_number"] == row["step_number"]), None)
    if not contact or contact["rejected"] or contact["unsubscribed"] or not step:
        finish(row, campaign, seat, now, "skipped", error="contact rejected / unsubscribed / step removed")
        return "skipped"
    t = step["type"]
    note_cap = INVITE_NOTE_MAX_SALES_NAV if (seat or {}).get("sales_navigator") else INVITE_NOTE_MAX

    if t in ("message", "voiceMessage"):
        gate = _linkedin_gate(row, campaign, contact, now, li.has_session(seat))
        if gate == "skip":
            finish(row, campaign, seat, now, "skipped", error="invitation not accepted")
            return "skipped"
        if gate == "wait":
            _set(row["id"], due_at=now + timedelta(hours=12))
            return "pending"
    if t in INVITATION_STEPS and contact.get("connection_degree") == 1:
        finish(row, campaign, seat, now, "accepted", error="already connected")
        return "accepted"

    if t == "email":
        return _execute_email(row, step, contact, campaign, seat, now)

    content = content_for(step, contact, campaign, _prior(row), note_cap)
    if not _automated(campaign, seat):
        _set(row["id"], state="manual", subject=content["subject"] or None, body=content["body"] or None)
        return "manual"

    url = contact["profile_url"]
    if not url:
        finish(row, campaign, seat, now, "skipped", error="no LinkedIn profile")
        return "skipped"
    if t in INVITATION_STEPS:
        if step.get("like_posts_before_invitation"):
            with contextlib.suppress(Exception):
                _quota(seat, "like")
                li.call("like_posts", {"url": url, "n": 1}, seat)
        _quota(seat, "invitation")
        res = li.call("invite", {"url": url, "note": content["body"] or None}, seat)
        if res.get("status") == "note_unavailable":
            res = li.call("invite", {"url": url}, seat)
        _sync_profile(contact, res)
        state = {"sent": "sent", "pending": "sent", "already_connected": "accepted"}.get(res.get("status"), "failed")
        finish(row, campaign, seat, now, state, body=content["body"] or None,
               error=None if state != "failed" else res.get("status"))
        return state
    if t in ("message", "voiceMessage"):
        _quota(seat, "message")
        args = {"url": url}
        if t == "voiceMessage":
            args.update({"text": "", "file": _download(step["url"])})
        elif campaign.get("split_linkedin_messages"):
            args["parts"] = split_paragraphs(content["body"])
        else:
            args["text"] = content["body"]
        res = li.call("message", args, seat)
        _sync_profile(contact, res)
        if res.get("status") == "not_connected":
            finish(row, campaign, seat, now, "skipped", error="not connected")
            return "skipped"
        finish(row, campaign, seat, now, "sent", body=content["body"])
        from sales.unibox import record_outbound

        record_outbound(channel="linkedin", seat_id=seat["id"], contact=contact,
                        body=content["body"] or "(voice message)", sender=seat.get("name"))
        return "sent"
    if t == "visitProfile":
        _quota(seat, "visit")
        _sync_profile(contact, li.call("visit", {"url": url}, seat))
        finish(row, campaign, seat, now, "sent")
        return "sent"
    if t == "likePosts":
        _quota(seat, "like")
        res = li.call("like_posts", {"url": url, "n": step.get("number_of_posts", 1)}, seat)
        finish(row, campaign, seat, now, "sent" if res.get("status") == "sent" else "skipped",
               error=None if res.get("status") == "sent" else "no recent posts")
        return "sent"
    raise ValueError(f"unhandled step type {t}")


def _sync_profile(contact: dict, res: dict | None) -> None:
    if not res:
        return
    deg = res.get("connection_degree")
    if deg and deg != contact.get("connection_degree"):
        with get_conn() as conn:
            conn.execute("UPDATE sales_contacts SET connection_degree = %s WHERE id = %s", (deg, contact["id"]))


def _download(url: str) -> str:
    import tempfile

    import httpx

    r = httpx.get(url, timeout=30, follow_redirects=True)
    r.raise_for_status()
    suffix = "." + (url.rsplit(".", 1)[-1][:4] if "." in url.rsplit("/", 1)[-1] else "m4a")
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as f:
        f.write(r.content)
        return f.name


def _pick_email_seat(campaign: dict) -> dict | None:
    for sid in campaign.get("email_seat_ids") or []:
        seat = emailer.get_seat(sid)
        if seat and seat.get("smtp_pass") and emailer.take_email_quota(seat):
            return seat
    return None


def _execute_email(row: dict, step: dict, contact: dict, campaign: dict, seat: dict | None,
                   now: datetime) -> str:
    if not contact.get("email") and not contact.get("email_enriched"):
        from sales.enrich import enrich_email

        contact = {**contact, **enrich_email(contact["id"])}
    addr = contact.get("email")
    if not addr:
        finish(row, campaign, seat, now, "skipped", error="no email found")
        return "skipped"
    if contact.get("email_status") == "bounced" or emailer.is_suppressed(addr):
        finish(row, campaign, seat, now, "skipped", error="bounced or suppressed")
        return "skipped"
    content = content_for(step, contact, campaign, _prior(row))
    if campaign.get("is_manual"):
        _set(row["id"], state="manual", subject=content["subject"], body=content["body"])
        return "manual"
    es = _pick_email_seat(campaign)
    if not es:
        raise QuotaReached("email")
    with get_conn() as conn:
        first = conn.execute(
            "SELECT s.subject, m.external_id FROM sales_campaign_status s "
            "JOIN sales_threads t ON t.contact_id = s.contact_id AND t.channel = 'email' "
            "JOIN sales_thread_messages m ON m.thread_id = t.id AND m.direction = 'out' "
            "WHERE s.contact_id = %s AND s.campaign_agent_id = %s AND s.type = 'email' AND s.state IN ('sent', 'delivered') "
            "ORDER BY s.step_number, m.sent_at LIMIT 1",
            (row["contact_id"], row["campaign_agent_id"]),
        ).fetchone()
    subject = content["subject"] or "quick question"
    in_reply_to = None
    if first and first["subject"]:
        subject = "Re: " + first["subject"].removeprefix("Re: ")
        in_reply_to = first["external_id"]
    mid = emailer.send(es, addr, subject, content["body"], status_id=row["id"], in_reply_to=in_reply_to)
    finish(row, campaign, seat, now, "sent", subject=subject, body=content["body"], seat_id=es["id"])
    from sales.unibox import record_outbound

    record_outbound(channel="email", seat_id=es["id"], contact=contact, body=content["body"],
                    external_message_id=mid, subject=subject, sender=es["email"])
    return "sent"


# -------------------------------------------------------------- acceptance --

def check_acceptances(campaign: dict, seat: dict | None, limit: int = 10) -> int:
    """Re-read profiles with an outstanding invitation to see if they
    accepted (degree 1). Bounded per tick - each check is a page view."""
    if not (seat and li.has_session(seat)):
        return 0
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT s.*, c.profile_url FROM sales_campaign_status s JOIN sales_contacts c ON c.id = s.contact_id
               WHERE s.campaign_agent_id = %s AND s.type IN ('invitation', 'invitationNote') AND s.state = 'sent'
                 AND s.done_at < now() - interval '1 day'
                 AND s.updated_at < now() - interval '12 hours'
               ORDER BY s.updated_at LIMIT %s""",
            (campaign["id"], limit),
        ).fetchall()
    accepted = 0
    for r in rows:
        try:
            p = li.call("profile", {"url": r["profile_url"]}, seat)
        except li.LinkedInError:
            break
        if p.get("connection_degree") == 1:
            _set(r["id"], state="accepted")
            with get_conn() as conn:
                conn.execute("UPDATE sales_contacts SET connection_degree = 1 WHERE id = %s", (r["contact_id"],))
            accepted += 1
        else:
            _set(r["id"], state="sent")  # bumps updated_at so we don't recheck for 12h
    return accepted


# ------------------------------------------------------------------- tick --

@contextlib.contextmanager
def _lock(campaign_id: int) -> Iterator[bool]:
    conn = psycopg.connect(settings.database_url, autocommit=True)
    try:
        got = conn.execute("SELECT pg_try_advisory_lock(%s, %s)", (7102, campaign_id)).fetchone()[0]
        yield got
        if got:
            conn.execute("SELECT pg_advisory_unlock(%s, %s)", (7102, campaign_id))
    finally:
        conn.close()


def tick(campaign_id: int, *, now: datetime | None = None, force: bool = False, max_steps: int = 50) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    campaign = get_campaign(campaign_id)
    if not campaign:
        raise ValueError(f"campaign {campaign_id} not found")
    if not campaign["active"] and not force:
        return {"campaign_id": campaign_id, "skipped": "inactive"}
    seat = li.get_seat(campaign.get("linkedin_seat_id"))
    if not force and not in_window(campaign, seat, now):
        return {"campaign_id": campaign_id, "skipped": "outside active days / before launch hour"}
    with _lock(campaign_id) as got:
        if not got:
            return {"campaign_id": campaign_id, "skipped": "already running"}
        enrolled = enroll(campaign, now)
        accepted = 0
        if seat and li.has_session(seat):  # read-only, also useful for manual campaigns
            with contextlib.suppress(li.LinkedInError):
                accepted = check_acceptances(campaign, seat)
        with get_conn() as conn:
            due = conn.execute(
                "SELECT * FROM sales_campaign_status WHERE campaign_agent_id = %s AND state = 'pending' "
                "AND due_at <= %s ORDER BY due_at, id LIMIT %s",
                (campaign_id, now, max_steps),
            ).fetchall()
        counts: dict[str, int] = {}
        blocked: set[str] = set()
        linkedin_down = None
        for row in due:
            kind = "email" if row["type"] == "email" else "linkedin"
            if kind in blocked:
                continue
            if kind == "linkedin" and linkedin_down:
                continue
            try:
                state = execute(row, campaign, seat, now)
                counts[state] = counts.get(state, 0) + 1
            except QuotaReached:
                blocked.add(kind)
            except (li.NoSession, li.LoggedOut) as e:
                linkedin_down = str(e)
                _set(row["id"], error=str(e)[:500])
            except Exception as e:  # noqa: BLE001 - one bad contact must not stop the campaign
                attempts = row["attempts"] + 1
                if attempts >= MAX_ATTEMPTS:
                    finish(row, campaign, seat, now, "failed", error=f"{type(e).__name__}: {e}"[:500], attempts=attempts)
                    counts["failed"] = counts.get("failed", 0) + 1
                else:
                    _set(row["id"], attempts=attempts, due_at=now + timedelta(hours=1), error=str(e)[:500])
        with get_conn() as conn:
            conn.execute("UPDATE campaign_agents SET last_tick_at = now() WHERE id = %s", (campaign_id,))
    if counts:
        report(f"  campaign {campaign_id}: {counts}", kind="status")
    return {"campaign_id": campaign_id, "enrolled": enrolled, "accepted": accepted, "steps": counts,
            "quota_reached": sorted(blocked), "linkedin_error": linkedin_down}


def active_campaign_ids() -> list[int]:
    with get_conn() as conn:
        return [r["id"] for r in conn.execute("SELECT id FROM campaign_agents WHERE active ORDER BY id").fetchall()]
