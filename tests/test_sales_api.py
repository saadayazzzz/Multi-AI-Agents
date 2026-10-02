"""HTTP layer: the API the console (and any MCP-style client) uses."""
from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient

from sales import signals as sig


@pytest.fixture
def client(clean):
    from sales.server import app

    with TestClient(app) as c:
        yield c


def _wait(client, job):
    for _ in range(100):
        j = client.get(f"/api/sales/jobs/{job['job']}").json()
        if j["status"] != "running":
            return j
        time.sleep(0.05)
    raise AssertionError("job never finished")


FULL = {
    "name": "Founder · Australia · Technology",
    "agent": {
        "target_job_titles": ["Founder", "CTO"], "target_industries": ["Technology"],
        "target_company_sizes": ["2-10", "11-50"], "target_locations": ["Australia"],
        "target_company_types": ["Startup"], "min_lead_score": 0.5, "lead_waterfall": False,
        "variables": [{"type": "SEARCH_KEYWORD", "value": '"automation"'}, {"type": "SEARCH_KEYWORD", "value": "mvp"},
                      {"type": "RECENT_ACTIVITY", "value": "true"}, {"type": "RECENTLY_CHANGED_JOB", "value": "true"}],
    },
    "campaign": {"is_manual": True, "goal": "demos", "steps": [
        {"type": "invitation", "likePostsBeforeInvitation": True}, {"type": "message", "messageMode": "ai"},
        {"type": "visitProfile"}]},
}


def test_full_cycle_creates_linked_inactive_trio(client):
    r = client.post("/api/sales/full-cycle", json=FULL)
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["campaign"]["active"] is False
    lst = client.get(f"/api/sales/lists/{body['list']['id']}").json()
    assert lst["campaign_id"] == body["campaign"]["id"]
    agents = client.get("/api/sales/agents").json()
    assert agents[0]["list_campaign_id"] == body["campaign"]["id"]


def test_full_cycle_rolls_back_list_on_bad_campaign(client):
    bad = {**FULL, "campaign": {"steps": [{"type": "message"}, {"type": "invitation"}]}}
    r = client.post("/api/sales/full-cycle", json=bad)
    assert r.status_code == 400 and "after a message" in r.json()["detail"]
    assert client.get("/api/sales/lists").json() == []


def test_validation_errors_are_400(client):
    lst = client.post("/api/sales/lists", json={"name": "L"}).json()
    r = client.post("/api/sales/agents", json={**FULL["agent"], "name": "x", "list_id": lst["id"],
                                               "variables": FULL["agent"]["variables"][:2]})
    assert r.status_code == 400 and "4-15" in r.json()["detail"]


def test_run_agent_job_logs_and_contacts(client, llm, monkeypatch):
    agent_id = client.post("/api/sales/full-cycle", json=FULL).json()["agent"]["id"]
    monkeypatch.setitem(sig.REGISTRY, "SEARCH_KEYWORD", lambda *_: [{
        "full_name": "Mia Chen", "profile_url": "https://www.linkedin.com/in/mia", "headline": "Founder @ Kite",
        "job_title": "Founder", "company": "Kite", "intent_type": "SEARCH_KEYWORD", "intent": "need automation",
    }])
    llm(json_out=lambda *a, **k: {"leads": [{"i": 0, "persona": 1, "company": 0.8, "service_provider": False,
                                             "job_title": None, "company_name": None, "industry": "Software",
                                             "location": "Sydney", "company_size": "2-10", "reason": "ok"}]})
    j = _wait(client, client.post(f"/api/sales/agents/{agent_id}/run").json())
    assert j["status"] == "done" and j["result"]["imported"] == 1
    logs = client.get(f"/api/sales/agents/{agent_id}/logs").json()
    assert logs[0]["imported"] == 1
    contacts = client.get("/api/sales/contacts?search=kite").json()
    assert contacts["total"] == 1
    cid = contacts["items"][0]["id"]
    detail = client.get(f"/api/sales/contacts/{cid}").json()
    assert detail["threads"] == [] and detail["lists"]
    assert client.get("/api/sales/intent-counts").json() == [{"intent_type": "SEARCH_KEYWORD", "count": 1}]
    ov = client.get("/api/sales/overview").json()
    assert ov["contacts"] == 1 and ov["agents"] == 1


def test_campaign_tick_tasks_and_complete(client):
    body = client.post("/api/sales/full-cycle", json=FULL).json()
    lid, cid = body["list"]["id"], body["campaign"]["id"]
    c = client.post("/api/sales/contacts", json={"full_name": "Ana Gomez", "profile_url": "linkedin.com/in/ana",
                                                  "list_ids": [lid]}).json()
    assert c["created"]
    j = _wait(client, client.post(f"/api/sales/campaigns/{cid}/tick?force=true").json())
    assert j["result"]["steps"] == {"manual": 1}
    tasks = client.get("/api/sales/tasks").json()
    assert tasks[0]["type"] == "invitation" and tasks[0]["full_name"] == "Ana Gomez"
    r = client.post(f"/api/sales/tasks/{tasks[0]['id']}/complete", json={"outcome": "accepted"})
    assert r.json()["state"] == "accepted"
    assert client.post(f"/api/sales/tasks/{tasks[0]['id']}/complete", json={}).status_code == 400
    stats = client.get(f"/api/sales/campaigns/{cid}/stats").json()
    assert stats["invitations_accepted"] == 1
    assert client.post(f"/api/sales/campaigns/{cid}/activate").json()["active"] is True
    assert [c["id"] for c in client.get("/api/sales/campaigns?status=active").json()] == [cid]
    assert client.get("/api/sales/campaigns?status=inactive").json() == []


def test_patch_campaign_steps_validates(client):
    cid = client.post("/api/sales/full-cycle", json=FULL).json()["campaign"]["id"]
    r = client.patch(f"/api/sales/campaigns/{cid}", json={"steps": [{"type": "likePosts", "numberOfPosts": 9}]})
    assert r.status_code == 400
    r = client.patch(f"/api/sales/campaigns/{cid}", json={"steps": [{"type": "visitProfile"}], "tone": "friendly"})
    assert r.status_code == 200 and r.json()["tone"] == "friendly" and len(r.json()["steps"]) == 1


def test_seats_hide_password(client):
    r = client.post("/api/sales/seats/email", json={"type": "google", "email": "me@gmail.com", "smtp_pass": "secret"})
    seat = r.json()
    assert seat["smtp_host"] == "smtp.gmail.com" and "smtp_pass" not in seat and seat["has_password"]
    li = client.post("/api/sales/seats/linkedin", json={"name": "Saad"}).json()
    assert li["automation_enabled"] is False
    assert client.patch(f"/api/sales/seats/linkedin/{li['id']}", json={"daily_invitations": 15}).json()["daily_invitations"] == 15


def test_tracking_pixel_and_website_visitor_script(client, monkeypatch):
    from sales import tracking

    assert client.get("/api/sales/t/o/nope.gif").headers["content-type"] == "image/gif"
    assert "not recognised" in client.get("/api/sales/t/u/nope").text
    lst = client.post("/api/sales/lists", json={"name": "V"}).json()
    a = client.post("/api/sales/agents", json={**{k: v for k, v in FULL["agent"].items() if k != "variables"},
                                               "name": "visitors", "list_id": lst["id"],
                                               "agent_type": "website-visitor"}).json()
    assert "/api/sales/track/" in a["tracking_script"]
    tid = a["tracking_script"].split("/api/sales/track/")[1].split(".js")[0]
    js = client.get(f"/api/sales/track/{tid}.js").text
    assert f"/api/sales/track/{tid}/hit" in js
    monkeypatch.setattr(tracking, "resolve_org", lambda ip: ("Kite Pty Ltd", "kite-pty-ltd"))
    r = client.post(f"/api/sales/track/{tid}/hit", content='{"u": "https://doers.studio/pricing", "r": ""}')
    assert r.json() == {"ok": True}
    assert client.get(f"/api/sales/agents/{a['id']}").json()["script_installed"] is True


def test_meta_and_console_served(client):
    meta = client.get("/api/sales/meta").json()
    assert len(meta["signals"]) == 17 and "email" in meta["step_types"]
    assert "Sales Engine" in client.get("/sales/").text
    assert client.get("/sales/app.js").status_code == 200


def test_api_token_guards_everything_but_tracking(client, monkeypatch):
    monkeypatch.setenv("SALES_API_TOKEN", "s3cret")
    assert client.get("/api/sales/lists").status_code == 401
    assert client.get("/api/sales/lists", headers={"Authorization": "Bearer nope"}).status_code == 401
    assert client.get("/api/sales/lists", headers={"Authorization": "Bearer s3cret"}).status_code == 200
    assert client.get("/api/sales/t/o/x.gif").status_code == 200
    assert client.get("/api/sales/t/u/x").status_code == 200
