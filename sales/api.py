"""REST API for the sales engine, mounted at /api/sales.

Covers every operation Gojiberry's MCP exposes (agents, campaigns, lists,
contacts, enrichment, directory, unibox, seats, logs) plus the pieces only
a self-hosted engine needs (manual tasks, tracking pixel, seat login).
"""
from __future__ import annotations

import base64
import os
import tempfile
import threading
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, PlainTextResponse, Response
from pydantic import BaseModel, Field

from config import settings
from sales import agents as agents_mod
from sales import campaigns as camp_mod
from sales import directory, emailer, enrich, executor, lists, runner, tracking, unibox
from sales import linkedin as li
from sales.constants import COMPANY_SIZES, COMPANY_TYPES, SIGNALS, STEP_TYPES

_PUBLIC_PREFIXES = ("/api/sales/t/", "/api/sales/track/")


def _auth(request: Request) -> None:
    """If SALES_API_TOKEN is set, every endpoint except the email-tracking
    and website-tracking ones (hit by recipients' mail clients and your
    site's visitors) needs `Authorization: Bearer <token>`. Set it whenever
    this server is reachable from outside your machine."""
    token = os.getenv("SALES_API_TOKEN")
    if not token or request.url.path.startswith(_PUBLIC_PREFIXES):
        return
    import hmac

    given = request.headers.get("authorization", "").removeprefix("Bearer ").strip()
    if not hmac.compare_digest(given, token):
        raise HTTPException(401, "missing or wrong API token")


router = APIRouter(prefix="/api/sales", tags=["sales"], dependencies=[Depends(_auth)])

_PIXEL = base64.b64decode("R0lGODlhAQABAIAAAAAAAP///ywAAAAAAQABAAACAUwAOw==")
_jobs: dict[str, dict] = {}


def _bg(key: str, fn, *args, **kwargs) -> dict:
    """Run a slow operation (agent run, campaign tick, inbox sync, login) in
    a thread; poll GET /api/sales/jobs/{key} for the result."""
    if _jobs.get(key, {}).get("status") == "running":
        return {"job": key, "status": "running"}
    _jobs[key] = {"status": "running"}

    def work() -> None:
        try:
            _jobs[key] = {"status": "done", "result": fn(*args, **kwargs)}
        except Exception as e:  # noqa: BLE001
            _jobs[key] = {"status": "failed", "error": f"{type(e).__name__}: {e}"}

    threading.Thread(target=work, daemon=True).start()
    return {"job": key, "status": "running"}


def _err(e: Exception) -> HTTPException:
    if isinstance(e, (agents_mod.AgentError, camp_mod.CampaignError, ValueError)):
        return HTTPException(400, str(e))
    if isinstance(e, li.NoSession):
        return HTTPException(409, str(e))
    return HTTPException(500, f"{type(e).__name__}: {e}")


def _404(row: Any, what: str) -> Any:
    if row is None:
        raise HTTPException(404, f"{what} not found")
    return row


@router.get("/jobs/{key}")
def job(key: str) -> dict:
    return _404(_jobs.get(key), "job")


@router.get("/meta")
def meta() -> dict:
    return {
        "signals": [{"type": t, "strength": s, "needs_linkedin": n, "description": d}
                    for t, (s, n, d) in SIGNALS.items()],
        "step_types": sorted(STEP_TYPES), "company_sizes": COMPANY_SIZES, "company_types": COMPANY_TYPES,
        "linkedin_automation_note": "LinkedIn write steps run only on seats with automation_enabled; "
                                    "otherwise they become manual tasks.",
    }


@router.get("/organization")
def organization() -> dict:
    return {
        "company_name": os.getenv("SALES_COMPANY_NAME"), "website": os.getenv("SALES_COMPANY_WEBSITE"),
        "description": os.getenv("SALES_OFFER"), "sender_name": os.getenv("SALES_SENDER_NAME"),
    }


@router.get("/overview")
def overview() -> dict:
    from db.database import get_conn

    with get_conn() as conn:
        q = lambda sql: conn.execute(sql).fetchone()["n"]  # noqa: E731
        return {
            "agents": q("SELECT COUNT(*) n FROM source_agents"),
            "agents_active": q("SELECT COUNT(*) n FROM source_agents WHERE NOT paused"),
            "campaigns": q("SELECT COUNT(*) n FROM campaign_agents"),
            "campaigns_active": q("SELECT COUNT(*) n FROM campaign_agents WHERE active"),
            "contacts": q("SELECT COUNT(*) n FROM sales_contacts"),
            "leads_7d": q("SELECT COUNT(*) n FROM sales_contacts WHERE created_at > now() - interval '7 days'"),
            "contacted": q("SELECT COUNT(DISTINCT contact_id) n FROM sales_campaign_status "
                           "WHERE state IN ('sent','delivered','accepted','answered')"),
            "replied": q("SELECT COUNT(DISTINCT contact_id) n FROM sales_campaign_status WHERE state = 'answered'"),
            "manual_tasks": q("SELECT COUNT(*) n FROM sales_campaign_status WHERE state = 'manual'"),
            "unread_threads": q("SELECT COUNT(*) n FROM sales_threads WHERE NOT seen"),
            "intent_counts": lists.intent_type_counts(),
        }


# ------------------------------------------------------------------ agents --

class AgentIn(BaseModel):
    name: str
    list_id: int
    target_job_titles: list[str]
    target_industries: list[str]
    target_company_sizes: list[str]
    target_locations: list[str]
    target_company_types: list[str]
    agent_type: str = "autopilot"
    variables: list[dict] = Field(default_factory=list)
    ignored_companies: list[str] = Field(default_factory=list)
    mandatory_keywords: list[str] = Field(default_factory=list)
    min_lead_score: float = 0.6
    exclude_service_providers: bool = True
    include_open_to_work_profiles: bool = False
    skip_icp_filter: bool = False
    lead_waterfall: bool = True
    additional_criteria: str = ""
    paused: bool = False
    max_credit_usage: int | None = None
    run_interval_minutes: int = 240
    leads_per_run: int = 25


@router.get("/agents")
def get_agents() -> list[dict]:
    return agents_mod.list_agents()


@router.post("/agents", status_code=201)
def post_agent(body: AgentIn) -> dict:
    try:
        return agents_mod.create_agent(**body.model_dump())
    except Exception as e:  # noqa: BLE001
        raise _err(e) from e


@router.get("/agents/{agent_id}")
def get_agent(agent_id: int) -> dict:
    return _404(agents_mod.get_agent(agent_id), "agent")


@router.patch("/agents/{agent_id}")
def patch_agent(agent_id: int, body: dict) -> dict:
    try:
        return agents_mod.update_agent(agent_id, body)
    except Exception as e:  # noqa: BLE001
        raise _err(e) from e


@router.delete("/agents/{agent_id}", status_code=204)
def del_agent(agent_id: int) -> Response:
    agents_mod.delete_agent(agent_id)
    return Response(status_code=204)


@router.post("/agents/{agent_id}/run", status_code=202)
def run_agent_now(agent_id: int, only_type: str | None = None) -> dict:
    _404(agents_mod.get_agent(agent_id), "agent")
    return _bg(f"agent-{agent_id}", runner.run_agent, agent_id, force=True, only_type=only_type)


@router.get("/agents/{agent_id}/logs")
def agent_logs(agent_id: int, date_from: str | None = None, date_to: str | None = None) -> list[dict]:
    return agents_mod.agent_logs(agent_id, date_from, date_to)


# ------------------------------------------------------------------- lists --

class ListIn(BaseModel):
    name: str
    custom_fields: dict | None = None


class IdsIn(BaseModel):
    contact_ids: list[int]


@router.get("/lists")
def get_lists() -> list[dict]:
    return lists.list_lists()


@router.post("/lists", status_code=201)
def post_list(body: ListIn) -> dict:
    return lists.create_list(body.name, body.custom_fields)


@router.get("/lists/{list_id}")
def get_list(list_id: int) -> dict:
    return _404(lists.get_list(list_id), "list")


@router.patch("/lists/{list_id}")
def patch_list(list_id: int, body: dict) -> dict:
    return _404(lists.update_list(list_id, body.get("name"), body.get("custom_fields")), "list")


@router.delete("/lists/{list_id}", status_code=204)
def del_list(list_id: int) -> Response:
    lists.delete_list(list_id)
    return Response(status_code=204)


@router.post("/lists/{list_id}/contacts")
def add_to_list(list_id: int, body: IdsIn) -> dict:
    return {"added": lists.add_contacts_to_list(list_id, body.contact_ids)}


@router.post("/lists/{list_id}/contacts/remove")
def remove_from_list(list_id: int, body: IdsIn) -> dict:
    return {"removed": lists.remove_contacts_from_list(list_id, body.contact_ids)}


@router.post("/lists/{list_id}/import")
async def import_csv(list_id: int, request: Request) -> dict:
    text = (await request.body()).decode("utf-8-sig", "replace")
    return lists.import_csv(list_id, text)


# ---------------------------------------------------------------- contacts --

@router.get("/contacts")
def get_contacts(list_id: int | None = None, agent: int | None = None, intent_type: str | None = None,
                 search: str | None = None, score_from: float | None = None, score_to: float | None = None,
                 date_from: str | None = None, date_to: str | None = None, page: int = 1, limit: int = 20) -> dict:
    return lists.list_contacts(list_id=list_id, agent_id=agent, intent_type=intent_type, search=search,
                               score_from=score_from, score_to=score_to, date_from=date_from, date_to=date_to,
                               page=page, limit=limit)


@router.post("/contacts", status_code=201)
def post_contact(body: dict) -> dict:
    list_ids = body.pop("list_ids", None) or []
    cid, created = lists.upsert_contact(body)
    for lid in list_ids:
        lists.add_contacts_to_list(lid, [cid])
    return {"id": cid, "created": created, "contact": lists.get_contact(cid)}


@router.get("/contacts/{contact_id}")
def get_contact(contact_id: int) -> dict:
    c = _404(lists.get_contact(contact_id), "contact")
    c["threads"] = unibox.threads_for_contact(contact_id)
    return c


@router.patch("/contacts/{contact_id}")
def patch_contact(contact_id: int, body: dict) -> dict:
    return _404(lists.update_contact(contact_id, body), "contact")


@router.post("/contacts/{contact_id}/reject")
def reject(contact_id: int, body: dict | None = None) -> dict:
    lists.reject_contact(contact_id, (body or {}).get("reason"))
    return {"ok": True}


@router.post("/contacts/{contact_id}/unreject")
def unreject(contact_id: int) -> dict:
    lists.unreject_contact(contact_id)
    return {"ok": True}


@router.post("/contacts/{contact_id}/enrich-email", status_code=202)
def enrich_email(contact_id: int) -> dict:
    return _bg(f"enrich-email-{contact_id}", enrich.enrich_email, contact_id)


@router.post("/contacts/{contact_id}/enrich-phone", status_code=202)
def enrich_phone(contact_id: int) -> dict:
    return _bg(f"enrich-phone-{contact_id}", enrich.enrich_phone, contact_id)


@router.get("/intent-counts")
def intent_counts() -> list[dict]:
    return lists.intent_type_counts()


# --------------------------------------------------------------- campaigns --

class CampaignIn(BaseModel):
    name: str
    steps: list[dict]
    list_ids: list[int]
    active: bool = False
    linkedin_seat_id: int | None = None
    email_seat_ids: list[int] = Field(default_factory=list)
    language: str | None = None
    tone: str = "conversational"
    goal: str = "demos"
    offer: str | None = None
    sender_name: str | None = None
    launch_hour: int = 9
    active_days: list[int] | None = None
    exclude_first_degree: bool = True
    split_linkedin_messages: bool = False
    skip_invitation_after_days: int = 7
    is_manual: bool = False


@router.get("/campaigns")
def get_campaigns(status: str = "all") -> list[dict]:
    out = camp_mod.list_campaigns(status)
    for c in out:
        c["stats"] = camp_mod.campaign_stats(c["id"])
    return out


@router.post("/campaigns", status_code=201)
def post_campaign(body: CampaignIn) -> dict:
    try:
        return camp_mod.create_campaign(**body.model_dump())
    except Exception as e:  # noqa: BLE001
        raise _err(e) from e


@router.get("/campaigns/{campaign_id}")
def get_campaign(campaign_id: int) -> dict:
    c = _404(camp_mod.get_campaign(campaign_id), "campaign")
    c["stats"] = camp_mod.campaign_stats(campaign_id)
    return c


@router.patch("/campaigns/{campaign_id}")
def patch_campaign(campaign_id: int, body: dict) -> dict:
    try:
        return camp_mod.update_campaign(campaign_id, body)
    except Exception as e:  # noqa: BLE001
        raise _err(e) from e


@router.delete("/campaigns/{campaign_id}", status_code=204)
def del_campaign(campaign_id: int) -> Response:
    camp_mod.delete_campaign(campaign_id)
    return Response(status_code=204)


@router.post("/campaigns/{campaign_id}/activate")
def activate(campaign_id: int) -> dict:
    return camp_mod.set_active(campaign_id, True)


@router.post("/campaigns/{campaign_id}/pause")
def pause(campaign_id: int) -> dict:
    return camp_mod.set_active(campaign_id, False)


@router.post("/campaigns/{campaign_id}/tick", status_code=202)
def tick(campaign_id: int, force: bool = False) -> dict:
    return _bg(f"tick-{campaign_id}", executor.tick, campaign_id, force=force)


@router.get("/campaigns/{campaign_id}/stats")
def stats(campaign_id: int) -> dict:
    return camp_mod.campaign_stats(campaign_id)


@router.get("/tasks")
def tasks(campaign_id: int | None = None) -> list[dict]:
    return executor.manual_tasks(campaign_id)


@router.post("/tasks/{status_id}/complete")
def complete_task(status_id: int, body: dict | None = None) -> dict:
    try:
        return executor.complete_manual(status_id, (body or {}).get("outcome", "sent"))
    except Exception as e:  # noqa: BLE001
        raise _err(e) from e


# ------------------------------------------------------------------- seats --

@router.get("/seats/linkedin")
def li_seats() -> list[dict]:
    return li.list_seats()


@router.post("/seats/linkedin", status_code=201)
def li_seat_new(body: dict) -> dict:
    return li.create_seat(**body)


@router.patch("/seats/linkedin/{seat_id}")
def li_seat_patch(seat_id: int, body: dict) -> dict:
    return _404(li.update_seat(seat_id, **body), "seat")


@router.delete("/seats/linkedin/{seat_id}", status_code=204)
def li_seat_del(seat_id: int) -> Response:
    li.delete_seat(seat_id)
    return Response(status_code=204)


@router.post("/seats/linkedin/{seat_id}/login", status_code=202)
def li_seat_login(seat_id: int) -> dict:
    seat = _404(li.get_seat(seat_id), "seat")
    return _bg(f"login-{seat_id}", li.login, seat)


@router.get("/seats/email")
def email_seats() -> list[dict]:
    return emailer.list_seats()


@router.post("/seats/email", status_code=201)
def email_seat_new(body: dict) -> dict:
    try:
        return emailer.create_seat(**body)
    except Exception as e:  # noqa: BLE001
        raise _err(e) from e


@router.patch("/seats/email/{seat_id}")
def email_seat_patch(seat_id: int, body: dict) -> dict:
    return _404(emailer.update_seat(seat_id, **body), "seat")


@router.delete("/seats/email/{seat_id}", status_code=204)
def email_seat_del(seat_id: int) -> Response:
    emailer.delete_seat(seat_id)
    return Response(status_code=204)


@router.post("/seats/email/{seat_id}/test")
def email_seat_test(seat_id: int, body: dict) -> dict:
    seat = _404(emailer.get_seat(seat_id), "seat")
    try:
        mid = emailer.send(seat, body["to"], "Test from your sales engine", "This seat can send email.")
        return {"status": "sent", "message_id": mid}
    except Exception as e:  # noqa: BLE001
        raise HTTPException(400, f"send failed: {e}") from e


# ------------------------------------------------------------------ unibox --

@router.get("/unibox/threads")
def threads(seat_id: int | None = None, channel: str | None = None, attendee_full_name: str | None = None,
            date_from: str | None = None, date_to: str | None = None, interested: bool | None = None,
            seen: bool | None = None, page: int = 1, limit: int = 20, order: str = "DESC") -> dict:
    return unibox.list_threads(seat_id=seat_id, channel=channel, attendee_full_name=attendee_full_name,
                               date_from=date_from, date_to=date_to, interested=interested, seen=seen,
                               page=page, limit=limit, order=order)


@router.get("/unibox/threads/{thread_id}")
def thread(thread_id: int) -> dict:
    unibox.update_thread(thread_id, seen=True)
    return {"messages": unibox.thread_messages(thread_id)}


@router.patch("/unibox/threads/{thread_id}")
def thread_patch(thread_id: int, body: dict) -> dict:
    unibox.update_thread(thread_id, seen=body.get("seen"), interested=body.get("interested"))
    return {"ok": True}


@router.post("/unibox/threads/{thread_id}/messages")
def thread_send(thread_id: int, body: dict) -> dict:
    attachment = None
    if body.get("file_base64"):
        suffix = os.path.splitext(body.get("file_name") or "attachment")[1]
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as f:
            f.write(base64.b64decode(body["file_base64"]))
        attachment = {"path": f.name, "name": body.get("file_name"), "mime": body.get("file_mime_type")}
    try:
        return unibox.send_message(thread_id, body.get("message") or "", attachment)
    except Exception as e:  # noqa: BLE001
        raise _err(e) from e


@router.post("/unibox/sync", status_code=202)
def unibox_sync() -> dict:
    from sales.scheduler import sync_all_inboxes

    return _bg("unibox-sync", sync_all_inboxes)


# --------------------------------------------------------------- directory --

@router.post("/directory/leads/search")
def dir_search(body: dict) -> dict:
    try:
        return directory.search_leads(**body)
    except Exception as e:  # noqa: BLE001
        raise _err(e) from e


@router.post("/directory/leads/reveal")
def dir_reveal(body: dict) -> dict:
    return directory.reveal_leads(body.get("ids") or [], body.get("list_id"))


@router.post("/directory/companies/search")
def dir_companies(body: dict) -> dict:
    return directory.search_companies(**body)


@router.post("/directory/companies/reveal")
def dir_companies_reveal(body: dict) -> list[dict]:
    return directory.reveal_companies(body.get("ids") or [])


@router.get("/directory/industries")
def dir_industries() -> dict:
    return directory.directory_industries()


# ------------------------------------------------------------- full cycle --

class FullCycleIn(BaseModel):
    """List + source agent + campaign agent in one call (Gojiberry's
    recommended 'Full Cycle' setup). The campaign is created inactive."""
    name: str
    agent: dict
    campaign: dict


@router.post("/full-cycle", status_code=201)
def full_cycle(body: FullCycleIn) -> dict:
    lst = lists.create_list(body.name)
    try:
        agent = agents_mod.create_agent(**{"name": body.name, **body.agent, "list_id": lst["id"]})
        camp = camp_mod.create_campaign(**{"name": body.name, "active": False, **body.campaign,
                                           "list_ids": [lst["id"]]})
    except Exception as e:  # noqa: BLE001
        lists.delete_list(lst["id"])
        raise _err(e) from e
    return {"list": lst, "agent": agent, "campaign": camp}


@router.post("/icp/from-site")
def icp_site(body: dict) -> dict:
    from ai_workflows.icp_builder.workflow import build_icp_from_site

    try:
        return build_icp_from_site(body["url"])
    except Exception as e:  # noqa: BLE001
        raise HTTPException(400, f"couldn't read that site: {e}") from e


@router.post("/icp/from-description")
def icp_desc(body: dict) -> dict:
    from ai_workflows.icp_builder.workflow import build_icp_from_description

    return build_icp_from_description(body["description"])


# ---------------------------------------------------------------- tracking --

@router.get("/t/o/{token}.gif")
def open_pixel(token: str) -> Response:
    emailer.record_open(token)
    return Response(_PIXEL, media_type="image/gif", headers={"Cache-Control": "no-store"})


@router.api_route("/t/u/{token}", methods=["GET", "POST"])
def unsubscribe(token: str) -> PlainTextResponse:
    ok = emailer.unsubscribe(token)
    return PlainTextResponse("You've been unsubscribed. Sorry for the bother." if ok else "Link not recognised.")


def _base(request: Request) -> str:
    return settings.public_base_url or str(request.base_url).rstrip("/")


@router.get("/track/{tid}.js")
def tracking_js(tid: str, request: Request) -> Response:
    if not tracking.agent_for_tracking_id(tid):
        return Response("", media_type="application/javascript")
    return Response(tracking.script_for(tid, _base(request)), media_type="application/javascript",
                    headers={"Access-Control-Allow-Origin": "*"})


@router.post("/track/{tid}/hit")
async def tracking_hit(tid: str, request: Request) -> JSONResponse:
    import json

    try:
        data = json.loads((await request.body()) or b"{}")
    except ValueError:
        data = {}
    ip = (request.headers.get("x-forwarded-for") or (request.client.host if request.client else "")).split(",")[0].strip()
    from fastapi.concurrency import run_in_threadpool

    await run_in_threadpool(tracking.record_hit, tid, ip, str(data.get("u") or ""), str(data.get("r") or ""),
                            request.headers.get("user-agent", ""))
    return JSONResponse({"ok": True}, headers={"Access-Control-Allow-Origin": "*"})
