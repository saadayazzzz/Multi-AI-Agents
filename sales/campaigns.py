"""Campaign agents: the outreach sequence, validated by Gojiberry's own rules.

Step rules (the API rejects violations, same as Gojiberry's create_campaign):
- types: invitation, invitationNote, message, voiceMessage, visitProfile,
  likePosts (LinkedIn) and email
- at most ONE connection-request step (invitation or invitationNote)
- an invitation can't come after a message / voiceMessage step
- delayAfterLastStep is an integer >= 1 (days), default 2
- message/email: messageMode 'ai' (written per contact) or 'same' (sent as-is,
  with [FirstName] [LastName] [Company]); 'same' needs the content, and a
  LinkedIn message is at most 1900 chars
- invitationNote needs a note (<= 180 chars, 280 with Sales Navigator)
- voiceMessage needs an audio url; likePosts numberOfPosts 1-3
- LinkedIn steps need a LinkedIn seat; email steps need email seat(s); several
  email seats only on email-only campaigns
"""
from __future__ import annotations

import uuid
from typing import Any

from db.database import get_conn
from sales.constants import (
    INVITATION_STEPS, INVITE_NOTE_MAX, INVITE_NOTE_MAX_SALES_NAV, LINKEDIN_MESSAGE_MAX,
    LINKEDIN_STEPS, STEP_TYPES,
)
from sales.db import jsonb


class CampaignError(ValueError):
    pass


def _g(step: dict, *names: str, default: Any = None) -> Any:
    """Accept both snake_case and Gojiberry's camelCase keys."""
    for n in names:
        if step.get(n) is not None:
            return step[n]
    return default


def validate_steps(steps: list[dict], sales_navigator: bool = False) -> list[dict]:
    if not steps:
        raise CampaignError("a campaign needs at least one step")
    out: list[dict] = []
    seen_invite = False
    seen_message = False
    for n, raw in enumerate(steps):
        t = raw.get("type")
        if t not in STEP_TYPES:
            raise CampaignError(f"step {n}: unknown type {t!r}")
        delay = _g(raw, "delay_after_last_step", "delayAfterLastStep", default=2)
        if not isinstance(delay, int) or isinstance(delay, bool) or delay < 1:
            raise CampaignError(f"step {n}: delayAfterLastStep must be an integer >= 1")
        step: dict[str, Any] = {
            "id": raw.get("id") or str(uuid.uuid4()),
            "type": t,
            "step_number": n,
            "delay_after_last_step": delay,
        }
        if t in INVITATION_STEPS:
            if seen_invite:
                raise CampaignError("only one connection request step (invitation / invitationNote) is allowed")
            if seen_message:
                raise CampaignError("an invitation can't come after a message or voiceMessage step")
            seen_invite = True
            step["like_posts_before_invitation"] = bool(
                _g(raw, "like_posts_before_invitation", "likePostsBeforeInvitation", default=False))
            if t == "invitationNote":
                note = (raw.get("note") or "").strip()
                cap = INVITE_NOTE_MAX_SALES_NAV if sales_navigator else INVITE_NOTE_MAX
                if not note:
                    raise CampaignError(f"step {n}: invitationNote needs a note")
                if len(note) > cap:
                    raise CampaignError(f"step {n}: invitation note is {len(note)} chars, max {cap}")
                step["note"] = note
        if t in ("message", "voiceMessage"):
            seen_message = True
        if t in ("message", "email"):
            content = raw.get("message") or ""
            mode = _g(raw, "message_mode", "messageMode") or ("same" if content.strip() else "ai")
            if mode not in ("ai", "same"):
                raise CampaignError(f"step {n}: messageMode must be 'ai' or 'same'")
            if mode == "same":
                if not content.strip():
                    raise CampaignError(f"step {n}: messageMode 'same' needs the message text")
                if t == "message" and len(content) > LINKEDIN_MESSAGE_MAX:
                    raise CampaignError(f"step {n}: LinkedIn message is {len(content)} chars, max {LINKEDIN_MESSAGE_MAX}")
                if t == "email" and not (raw.get("subject") or "").strip():
                    raise CampaignError(f"step {n}: an email in 'same' mode needs a subject")
            step["message_mode"] = mode
            step["message"] = content
            if t == "email":
                step["subject"] = raw.get("subject") or ""
            if t == "message":
                step["gif"] = raw.get("gif")
        if t == "voiceMessage":
            if not raw.get("url"):
                raise CampaignError(f"step {n}: voiceMessage needs an audio url")
            step["url"] = raw["url"]
        if t == "likePosts":
            k = _g(raw, "number_of_posts", "numberOfPosts", default=1)
            if not isinstance(k, int) or not 1 <= k <= 3:
                raise CampaignError(f"step {n}: numberOfPosts must be 1-3")
            step["number_of_posts"] = k
        out.append(step)
    return out


def _check_seats(steps: list[dict], linkedin_seat_id: int | None, email_seat_ids: list[int], is_manual: bool) -> None:
    has_li = any(s["type"] in LINKEDIN_STEPS for s in steps)
    has_email = any(s["type"] == "email" for s in steps)
    if is_manual:
        return
    if has_li and not linkedin_seat_id:
        raise CampaignError("this campaign has LinkedIn steps - linkedin_seat_id is required")
    if not has_li and linkedin_seat_id:
        raise CampaignError("linkedin_seat_id isn't allowed on an email-only campaign")
    if has_email and not email_seat_ids:
        raise CampaignError("this campaign has email steps - email_seat_ids is required")
    if has_li and len(email_seat_ids) > 1:
        raise CampaignError("several email seats are only allowed on email-only campaigns")
    if len(email_seat_ids) > 100:
        raise CampaignError("at most 100 email seats")
    with get_conn() as conn:
        if linkedin_seat_id and not conn.execute("SELECT 1 FROM linkedin_seats WHERE id = %s", (linkedin_seat_id,)).fetchone():
            raise CampaignError(f"LinkedIn seat {linkedin_seat_id} not found")
        if email_seat_ids:
            n = conn.execute("SELECT COUNT(*) n FROM email_seats WHERE id = ANY(%s)", (email_seat_ids,)).fetchone()["n"]
            if n != len(set(email_seat_ids)):
                raise CampaignError("unknown email seat id")


def _sales_nav(seat_id: int | None) -> bool:
    if not seat_id:
        return False
    with get_conn() as conn:
        r = conn.execute("SELECT sales_navigator FROM linkedin_seats WHERE id = %s", (seat_id,)).fetchone()
    return bool(r and r["sales_navigator"])


def create_campaign(
    *, name: str, steps: list[dict], list_ids: list[int], active: bool = False,
    linkedin_seat_id: int | None = None, email_seat_ids: list[int] | None = None,
    language: str | None = None, tone: str = "conversational", goal: str = "demos",
    offer: str | None = None, sender_name: str | None = None, launch_hour: int = 9,
    active_days: list[int] | None = None, exclude_first_degree: bool = True,
    split_linkedin_messages: bool = False, skip_invitation_after_days: int = 7,
    is_manual: bool = False,
) -> dict:
    if not list_ids:
        raise CampaignError("at least one list is required")
    email_seat_ids = [int(x) for x in (email_seat_ids or [])]
    norm = validate_steps(steps, _sales_nav(linkedin_seat_id))
    _check_seats(norm, linkedin_seat_id, email_seat_ids, is_manual)
    if not 0 <= launch_hour <= 23:
        raise CampaignError("launch_hour is 0-23")
    with get_conn() as conn:
        found = conn.execute("SELECT COUNT(*) n FROM sales_lists WHERE id = ANY(%s)", (list_ids,)).fetchone()["n"]
        if found != len(set(list_ids)):
            raise CampaignError("unknown list id")
        row = conn.execute(
            """
            INSERT INTO campaign_agents (
                name, steps, active, linkedin_seat_id, email_seat_ids, language, tone, goal, offer,
                sender_name, launch_hour, active_days, exclude_first_degree, split_linkedin_messages,
                skip_invitation_after_days, is_manual
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id
            """,
            (name, jsonb(norm), active, linkedin_seat_id, email_seat_ids, language, tone, goal, offer,
             sender_name, launch_hour, active_days, exclude_first_degree, split_linkedin_messages,
             skip_invitation_after_days, is_manual),
        ).fetchone()
        conn.execute(
            "UPDATE sales_lists SET campaign_agent_id = %s, updated_at = now() WHERE id = ANY(%s)",
            (row["id"], list_ids),
        )
    return get_campaign(row["id"])


_UPDATABLE = {
    "name", "language", "tone", "goal", "offer", "sender_name", "launch_hour", "active_days",
    "exclude_first_degree", "split_linkedin_messages", "skip_invitation_after_days", "is_manual",
    "linkedin_seat_id", "email_seat_ids",
}


def update_campaign(campaign_id: int, fields: dict[str, Any]) -> dict:
    camp = get_campaign(campaign_id)
    if not camp:
        raise CampaignError(f"campaign {campaign_id} not found")
    merged = {**camp, **{k: v for k, v in fields.items() if v is not None}}
    steps = camp["steps"]
    if fields.get("steps") is not None:
        steps = validate_steps(fields["steps"], _sales_nav(merged.get("linkedin_seat_id")))
    _check_seats(steps, merged.get("linkedin_seat_id"), list(merged.get("email_seat_ids") or []),
                 bool(merged.get("is_manual")))
    sets, vals = ["steps = %s"], [jsonb(steps)]
    for k, v in fields.items():
        if k in _UPDATABLE and v is not None:
            sets.append(f"{k} = %s")
            vals.append(v)
    with get_conn() as conn:
        conn.execute(
            f"UPDATE campaign_agents SET {', '.join(sets)}, updated_at = now() WHERE id = %s",
            (*vals, campaign_id),
        )
        if fields.get("list_ids") is not None:
            conn.execute("UPDATE sales_lists SET campaign_agent_id = NULL WHERE campaign_agent_id = %s", (campaign_id,))
            conn.execute("UPDATE sales_lists SET campaign_agent_id = %s WHERE id = ANY(%s)",
                         (campaign_id, fields["list_ids"]))
        if fields.get("steps") is not None:
            # Rebuild not-yet-started steps against the new sequence.
            conn.execute(
                "DELETE FROM sales_campaign_status WHERE campaign_agent_id = %s AND state IN ('waiting', 'pending')",
                (campaign_id,),
            )
    return get_campaign(campaign_id)


def set_active(campaign_id: int, active: bool) -> dict:
    with get_conn() as conn:
        conn.execute("UPDATE campaign_agents SET active = %s, updated_at = now() WHERE id = %s", (active, campaign_id))
    return get_campaign(campaign_id)


def get_campaign(campaign_id: int) -> dict | None:
    with get_conn() as conn:
        c = conn.execute("SELECT * FROM campaign_agents WHERE id = %s", (campaign_id,)).fetchone()
        if c:
            c["list_ids"] = [r["id"] for r in conn.execute(
                "SELECT id FROM sales_lists WHERE campaign_agent_id = %s", (campaign_id,)
            ).fetchall()]
    return c


def list_campaigns(status: str = "all") -> list[dict]:
    where = {"active": "WHERE active", "inactive": "WHERE NOT active"}.get(status, "")
    with get_conn() as conn:
        rows = conn.execute(f"SELECT * FROM campaign_agents {where} ORDER BY id DESC").fetchall()
        for c in rows:
            c["list_ids"] = [r["id"] for r in conn.execute(
                "SELECT id FROM sales_lists WHERE campaign_agent_id = %s", (c["id"],)
            ).fetchall()]
    return rows


def delete_campaign(campaign_id: int) -> None:
    with get_conn() as conn:
        conn.execute("DELETE FROM campaign_agents WHERE id = %s", (campaign_id,))


def campaign_stats(campaign_id: int) -> dict:
    """Gojiberry's own definition: a reply = any message/voiceMessage/email
    step 'answered'; reply rate = replied contacts / contacts in the lists."""
    with get_conn() as conn:
        total = conn.execute(
            "SELECT COUNT(DISTINCT lc.contact_id) n FROM sales_list_contacts lc "
            "JOIN sales_lists l ON l.id = lc.list_id WHERE l.campaign_agent_id = %s",
            (campaign_id,),
        ).fetchone()["n"]
        by_step = conn.execute(
            "SELECT step_number, type, state, COUNT(*)::int n FROM sales_campaign_status "
            "WHERE campaign_agent_id = %s GROUP BY step_number, type, state ORDER BY step_number",
            (campaign_id,),
        ).fetchall()
        replied = conn.execute(
            "SELECT COUNT(DISTINCT contact_id) n FROM sales_campaign_status WHERE campaign_agent_id = %s "
            "AND type IN ('message', 'voiceMessage', 'email') AND state = 'answered'",
            (campaign_id,),
        ).fetchone()["n"]
        contacted = conn.execute(
            "SELECT COUNT(DISTINCT contact_id) n FROM sales_campaign_status WHERE campaign_agent_id = %s "
            "AND state IN ('sent', 'delivered', 'accepted', 'answered')",
            (campaign_id,),
        ).fetchone()["n"]
        accepted = conn.execute(
            "SELECT COUNT(*) n FROM sales_campaign_status WHERE campaign_agent_id = %s "
            "AND type IN ('invitation', 'invitationNote') AND state = 'accepted'",
            (campaign_id,),
        ).fetchone()["n"]
        invites = conn.execute(
            "SELECT COUNT(*) n FROM sales_campaign_status WHERE campaign_agent_id = %s "
            "AND type IN ('invitation', 'invitationNote') AND state IN ('sent', 'accepted')",
            (campaign_id,),
        ).fetchone()["n"]
        manual = conn.execute(
            "SELECT COUNT(*) n FROM sales_campaign_status WHERE campaign_agent_id = %s AND state = 'manual'",
            (campaign_id,),
        ).fetchone()["n"]
    return {
        "contacts": total, "contacted": contacted, "answered": replied,
        "reply_rate": round(replied / total, 4) if total else 0.0,
        "invitations_sent": invites, "invitations_accepted": accepted,
        "acceptance_rate": round(accepted / invites, 4) if invites else 0.0,
        "manual_tasks_open": manual, "by_step": by_step,
    }
