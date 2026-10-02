"""End-to-end against a real Postgres: agents, runner, campaigns, executor,
unibox, email, enrichment, directory. LinkedIn and the LLM are stubbed."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from db.database import get_conn
from sales import agents, campaigns, directory, emailer, executor, lists, runner, unibox
from sales import linkedin as li
from sales import signals as sig

NOW = datetime(2026, 10, 5, 10, 0, tzinfo=timezone.utc)  # Monday 10:00 UTC


def _cands(n, start=0, **extra):
    return [{
        "full_name": f"Person {i}", "profile_url": f"https://www.linkedin.com/in/p{i}",
        "headline": f"Founder @ Co{i}", "job_title": "Founder", "company": f"Co{i}",
        "intent_type": "SEARCH_KEYWORD", "intent": "posted about ai agents", "signal_value": "ai agents",
        "intent_at": NOW.isoformat(), **extra,
    } for i in range(start, start + n)]


def _score_all(persona=1.0, company=1.0, provider_idx=()):
    def json_out(system, user, schema, max_tokens=0):
        n = user.count("\n[")
        n = sum(1 for line in user.splitlines() if line.startswith("["))
        return {"leads": [{"i": i, "persona": persona, "company": company, "service_provider": i in provider_idx,
                           "job_title": None, "company_name": None, "industry": "Software", "location": "Sydney",
                           "company_size": "2-10", "reason": "fits"} for i in range(n)]}
    return json_out


def _agent(list_id, **kw):
    base = dict(
        name="Founders AU", list_id=list_id, target_job_titles=["Founder", "CEO"],
        target_industries=["Software"], target_company_sizes=["1-10 employees", "11-50"],
        target_locations=["Australia"], target_company_types=["Startup"],
        variables=[{"type": "SEARCH_KEYWORD", "value": f"kw{i}"} for i in range(4)],
        min_lead_score=0.6, leads_per_run=10,
    )
    base.update(kw)
    return agents.create_agent(**base)


# ------------------------------------------------------------------ agents --

def test_agent_requires_list(clean):
    with pytest.raises(agents.AgentError, match="list 999 not found"):
        _agent(999)


def test_agent_normalizes_sizes_and_links_list(clean):
    lst = lists.create_list("L")
    a = _agent(lst["id"])
    assert a["target_company_sizes"] == ["2-10", "11-50"]
    assert a["list_id"] == lst["id"] and a["list_campaign_id"] is None


def test_runner_imports_scores_dedupes_and_logs(clean, llm, monkeypatch):
    lst = lists.create_list("L")
    a = _agent(lst["id"], lead_waterfall=False)
    monkeypatch.setitem(sig.REGISTRY, "SEARCH_KEYWORD", lambda *_: _cands(5))
    llm(json_out=_score_all())
    r = runner.run_agent(a["id"])
    assert r["imported"] == 5 and len(r["runs"]) == 1  # waterfall off: one variable per run
    assert lists.get_list(lst["id"])["contact_count"] == 5
    c = lists.list_contacts(list_id=lst["id"])["items"][0]
    assert c["agent_id"] == a["id"] and float(c["total_score"]) > 2.5 and c["scoring"]["persona"] == 1.0
    # second run: same people -> all duplicates, rotated to the next variable
    r2 = runner.run_agent(a["id"])
    assert r2["imported"] == 0
    logs = agents.agent_logs(a["id"])
    assert [l["variable_value"] for l in logs] == ["kw1", "kw0"]
    assert logs[0]["duplicates"] == 5 and logs[1]["imported"] == 5
    v = agents.get_agent(a["id"])["variables"]
    assert v[0]["nb_results_last_launch"] == 5 and v[0]["strength"] == "high" and v[0]["last_usage"]


def test_runner_filters(clean, llm, monkeypatch):
    lst = lists.create_list("L")
    a = _agent(lst["id"], ignored_companies=["Co1"], mandatory_keywords=["agents"], lead_waterfall=False)
    people = _cands(4)
    people[2]["intent"] = "posted about cooking"           # fails mandatory keyword
    people[2]["headline"] = "Founder @ Co2"
    people[3]["open_to_work"] = True                       # excluded by default
    monkeypatch.setitem(sig.REGISTRY, "SEARCH_KEYWORD", lambda *_: people)
    llm(json_out=_score_all())
    r = runner.run_agent(a["id"])
    log = agents.agent_logs(a["id"])[0]
    assert r["imported"] == 1 and log["filtered"] == 3


def test_runner_threshold_and_service_providers(clean, llm, monkeypatch):
    lst = lists.create_list("L")
    a = _agent(lst["id"], min_lead_score=0.8, lead_waterfall=False)
    monkeypatch.setitem(sig.REGISTRY, "SEARCH_KEYWORD", lambda *_: _cands(3))
    llm(json_out=_score_all(persona=0.4, company=0.9, provider_idx=(0,)))
    r = runner.run_agent(a["id"])
    log = agents.agent_logs(a["id"])[0]
    assert r["imported"] == 0 and log["filtered"] == 1 and log["below_score"] == 2


def test_runner_waterfall_and_failure_isolation(clean, llm, monkeypatch):
    lst = lists.create_list("L")
    a = _agent(lst["id"], leads_per_run=6, variables=[
        {"type": "SEARCH_KEYWORD", "value": "a"}, {"type": "HIRING", "value": "ops"},
        {"type": "VISITED_PROFILE", "value": "true"}, {"type": "TECHNOLOGY", "value": "hubspot"},
    ])
    calls = []

    def boom(*_):
        calls.append("hiring")
        raise RuntimeError("search down")

    monkeypatch.setitem(sig.REGISTRY, "SEARCH_KEYWORD", lambda *_: (calls.append("kw"), _cands(4))[1])
    monkeypatch.setitem(sig.REGISTRY, "HIRING", boom)
    monkeypatch.setitem(sig.REGISTRY, "VISITED_PROFILE", lambda *_: (calls.append("visit"), _cands(4, start=10))[1])
    monkeypatch.setitem(sig.REGISTRY, "TECHNOLOGY", lambda *_: (calls.append("tech"), _cands(4, start=20))[1])
    llm(json_out=_score_all())
    r = runner.run_agent(a["id"])
    assert calls == ["kw", "hiring", "visit"]  # stops once 6 reached; tech never ran
    assert r["imported"] == 6
    states = {l["variable_type"]: l["status"] for l in agents.agent_logs(a["id"])}
    assert states == {"SEARCH_KEYWORD": "success", "HIRING": "failed", "VISITED_PROFILE": "success"}


def test_linkedin_signal_without_session_is_skipped(clean, llm, monkeypatch):
    lst = lists.create_list("L")
    a = _agent(lst["id"], lead_waterfall=False)
    monkeypatch.setattr(li, "has_session", lambda seat=None: False)
    r = runner.run_agent(a["id"])
    assert r["runs"][0]["skipped"].startswith("needs a logged-in")
    assert agents.agent_logs(a["id"])[0]["status"] == "skipped"


def test_paused_agent_not_run_and_due_list(clean, llm, monkeypatch):
    lst = lists.create_list("L")
    a = _agent(lst["id"], paused=True)
    assert runner.run_agent(a["id"]) == {"agent_id": a["id"], "skipped": "paused"}
    assert runner.due_agents() == []
    agents.update_agent(a["id"], {"paused": False})
    assert runner.due_agents() == [a["id"]]


def test_skip_icp_filter_needs_no_llm(clean, monkeypatch):
    lst = lists.create_list("L")
    a = _agent(lst["id"], skip_icp_filter=True, lead_waterfall=False)
    monkeypatch.setitem(sig.REGISTRY, "SEARCH_KEYWORD", lambda *_: _cands(2))
    assert runner.run_agent(a["id"])["imported"] == 2


def test_scoring_falls_back_to_heuristic(clean, llm, monkeypatch):
    lst = lists.create_list("L")
    a = _agent(lst["id"], min_lead_score=0.5, lead_waterfall=False)
    monkeypatch.setitem(sig.REGISTRY, "SEARCH_KEYWORD", lambda *_: _cands(1))

    def broken(*a, **k):
        raise RuntimeError("quota")

    llm(json_out=broken)
    assert runner.run_agent(a["id"])["imported"] == 1
    c = lists.list_contacts()["items"][0]
    assert c["scoring"]["reason"].startswith("heuristic")


# --------------------------------------------------------------- campaigns --

def _contacts_in_list(lst_id, n=2, **extra):
    ids = []
    for i in range(n):
        cid, _ = lists.upsert_contact({"full_name": f"Sara Ali{i}", "profile_url": f"https://www.linkedin.com/in/s{i}",
                                       "company": "Acme", "job_title": "CEO", **extra})
        ids.append(cid)
    lists.add_contacts_to_list(lst_id, ids)
    return ids


def test_campaign_requires_seats_unless_manual(clean):
    lst = lists.create_list("L")
    with pytest.raises(campaigns.CampaignError, match="linkedin_seat_id is required"):
        campaigns.create_campaign(name="c", steps=[{"type": "invitation"}], list_ids=[lst["id"]])
    with pytest.raises(campaigns.CampaignError, match="email_seat_ids is required"):
        campaigns.create_campaign(name="c", steps=[{"type": "email"}], list_ids=[lst["id"]])
    c = campaigns.create_campaign(name="c", steps=[{"type": "invitation"}], list_ids=[lst["id"]], is_manual=True)
    assert c["active"] is False and c["list_ids"] == [lst["id"]]
    assert lists.get_list(lst["id"])["campaign_id"] == c["id"]


def test_manual_sequence_end_to_end(clean, llm):
    lst = lists.create_list("L")
    c1, c2 = _contacts_in_list(lst["id"], 2)
    camp = campaigns.create_campaign(
        name="c", list_ids=[lst["id"]], is_manual=True, active=True,
        steps=[{"type": "invitationNote", "note": "Hi [FirstName], saw [Company]"},
               {"type": "message", "message": "Thanks for connecting [FirstName]!", "delay_after_last_step": 2},
               {"type": "visitProfile"}],
    )
    r = executor.tick(camp["id"], now=NOW)
    assert r["enrolled"] == 2 and r["steps"] == {"manual": 2}
    tasks = executor.manual_tasks(camp["id"])
    assert {t["body"] for t in tasks} == {"Hi Sara, saw Acme"}
    executor.complete_manual(tasks[0]["id"], "sent", now=NOW)
    st = {r["step_number"]: r for r in lists.get_contact(tasks[0]["contact_id"])["campaign_status"]}
    assert st[0]["state"] == "sent" and st[1]["state"] == "pending"
    assert st[1]["due_at"] == datetime(2026, 10, 7, 9, tzinfo=timezone.utc)  # +2 days, launch hour
    # nothing more due today for that contact
    assert executor.tick(camp["id"], now=NOW)["steps"] == {}
    # two days later the DM is due; no session -> handed to the user
    later = st[1]["due_at"] + timedelta(minutes=1)
    assert executor.tick(camp["id"], now=later)["steps"] == {"manual": 1}
    assert any(t["body"] == "Thanks for connecting Sara!" for t in executor.manual_tasks(camp["id"]))
    stats = campaigns.campaign_stats(camp["id"])
    assert stats["contacts"] == 2 and stats["contacted"] == 1 and stats["manual_tasks_open"] == 2


def test_tick_outside_window_and_inactive(clean):
    lst = lists.create_list("L")
    camp = campaigns.create_campaign(name="c", list_ids=[lst["id"]], is_manual=True,
                                     steps=[{"type": "visitProfile"}], launch_hour=9)
    assert executor.tick(camp["id"], now=NOW)["skipped"] == "inactive"
    campaigns.set_active(camp["id"], True)
    sat = datetime(2026, 10, 3, 12, tzinfo=timezone.utc)
    assert "outside" in executor.tick(camp["id"], now=sat)["skipped"]
    early = datetime(2026, 10, 5, 7, tzinfo=timezone.utc)
    assert "outside" in executor.tick(camp["id"], now=early)["skipped"]


def test_first_degree_excluded_and_rejected_skipped(clean):
    lst = lists.create_list("L")
    a, b = _contacts_in_list(lst["id"], 2)
    lists.update_contact(a, {"connection_degree": 1})
    camp = campaigns.create_campaign(name="c", list_ids=[lst["id"]], is_manual=True, active=True,
                                     steps=[{"type": "visitProfile"}, {"type": "visitProfile"}])
    assert executor.tick(camp["id"], now=NOW)["enrolled"] == 1
    lists.reject_contact(b, "not a fit")
    st = lists.get_contact(b)["campaign_status"]
    assert {s["state"] for s in st} == {"skipped"}


def test_reply_marks_answered_and_stops_sequence(clean):
    lst = lists.create_list("L")
    (cid,) = _contacts_in_list(lst["id"], 1)
    camp = campaigns.create_campaign(name="c", list_ids=[lst["id"]], is_manual=True, active=True,
                                     steps=[{"type": "message", "message": "hi"}, {"type": "message", "message": "bump"}])
    executor.tick(camp["id"], now=NOW)
    executor.complete_manual(executor.manual_tasks()[0]["id"], "sent", now=NOW)
    contact = lists.get_contact(cid)
    assert unibox.record_inbound(channel="linkedin", seat_id=None, external_thread_id="t1", sender="Sara",
                                 body="Sounds interesting, tell me more", sent_at=NOW, external_message_id="m1",
                                 attendee_profile_url=contact["profile_url"])
    states = [s["state"] for s in lists.get_contact(cid)["campaign_status"]]
    assert states == ["answered", "skipped"]
    assert campaigns.campaign_stats(camp["id"])["reply_rate"] == 1.0
    th = unibox.list_threads()["items"]
    assert len(th) == 1 and th[0]["seen"] is False and th[0]["contact_id"] == cid
    # duplicate delivery is ignored
    assert not unibox.record_inbound(channel="linkedin", seat_id=None, external_thread_id="t1", sender="Sara",
                                     body="Sounds interesting, tell me more", sent_at=NOW, external_message_id="m1",
                                     attendee_profile_url=contact["profile_url"])


def test_invitation_gate_waits_then_skips(clean, monkeypatch):
    seat = li.create_seat(name="me", automation_enabled=False)
    monkeypatch.setattr(li, "has_session", lambda s=None: True)
    monkeypatch.setattr(executor.li, "has_session", lambda s=None: True)
    monkeypatch.setattr(li, "call", lambda *a, **k: {"connection_degree": 2})
    lst = lists.create_list("L")
    (cid,) = _contacts_in_list(lst["id"], 1)
    camp = campaigns.create_campaign(name="c", list_ids=[lst["id"]], linkedin_seat_id=seat["id"], active=True,
                                     skip_invitation_after_days=7,
                                     steps=[{"type": "invitation"}, {"type": "message", "message": "hi", "delay_after_last_step": 1}])
    executor.tick(camp["id"], now=NOW)  # automation off -> manual invitation task
    executor.complete_manual(executor.manual_tasks()[0]["id"], "sent", now=NOW)
    st = lists.get_contact(cid)["campaign_status"]
    msg_due = st[1]["due_at"]
    assert executor.tick(camp["id"], now=msg_due + timedelta(minutes=1))["steps"] == {"pending": 1}  # waiting for acceptance
    with get_conn() as conn:
        conn.execute("UPDATE sales_campaign_status SET done_at = now() - interval '8 days' WHERE step_number = 0")
        conn.execute("UPDATE sales_campaign_status SET due_at = %s WHERE step_number = 1", (NOW,))
    assert executor.tick(camp["id"], now=NOW + timedelta(minutes=1))["steps"] == {"skipped": 1}


def test_automated_linkedin_steps_use_quota(clean, monkeypatch):
    seat = li.create_seat(name="me", automation_enabled=True, daily_invitations=1)
    monkeypatch.setattr(li, "has_session", lambda s=None: True)
    sent = []

    def fake_call(mode, args=None, seat=None, **k):
        sent.append(mode)
        return {"status": "sent", "connection_degree": 2}

    monkeypatch.setattr(li, "call", fake_call)
    lst = lists.create_list("L")
    _contacts_in_list(lst["id"], 3)
    camp = campaigns.create_campaign(name="c", list_ids=[lst["id"]], linkedin_seat_id=seat["id"], active=True,
                                     steps=[{"type": "invitation"}])
    r = executor.tick(camp["id"], now=NOW)
    assert r["steps"] == {"sent": 1} and r["quota_reached"] == ["linkedin"]
    assert sent.count("invite") == 1
    assert li.used_today("linkedin", seat["id"], "invitation") == 1


def test_email_step_sends_threads_and_respects_suppression(clean, llm, monkeypatch):
    seat = emailer.create_seat(email="me@doers.studio", smtp_host="smtp.x", smtp_pass="pw", warmup_enabled=False)
    outbox = []

    def fake_send(s, to, subject, body, *, status_id=None, in_reply_to=None):
        outbox.append((to, subject, in_reply_to))
        return f"<m{len(outbox)}@doers.studio>"

    monkeypatch.setattr(emailer, "send", fake_send)
    lst = lists.create_list("L")
    a, b, c = _contacts_in_list(lst["id"], 3)
    lists.update_contact(a, {"email": "a@acme.com"})
    lists.update_contact(b, {"email": "b@acme.com"})
    with get_conn() as conn:
        conn.execute("INSERT INTO suppression (email) VALUES ('b@acme.com')")
        conn.execute("UPDATE sales_contacts SET email_enriched = true WHERE id = %s", (c,))
    camp = campaigns.create_campaign(
        name="c", list_ids=[lst["id"]], email_seat_ids=[seat["id"]], active=True,
        steps=[{"type": "email", "subject": "hi [FirstName]", "message": "Hello [FirstName]"},
               {"type": "email", "subject": "x", "message": "Following up", "delay_after_last_step": 1}],
    )
    r = executor.tick(camp["id"], now=NOW)
    assert r["steps"] == {"sent": 1, "skipped": 2}
    assert outbox == [("a@acme.com", "hi Sara", None)]
    st = {s["step_number"]: s for s in lists.get_contact(a)["campaign_status"]}
    executor.tick(camp["id"], now=st[1]["due_at"] + timedelta(minutes=1))
    assert outbox[1] == ("a@acme.com", "Re: hi Sara", "<m1@doers.studio>")  # threaded follow-up
    th = unibox.list_threads(channel="email")["items"]
    assert len(th) == 1 and len(unibox.thread_messages(th[0]["id"])) == 2


def test_warmup_cap_ramps(clean):
    s = emailer.create_seat(email="w@x.com", smtp_host="h", smtp_pass="p", daily_email_max=30)
    raw = emailer.get_seat(s["id"])
    assert emailer.warmup_cap(raw) == 5
    raw["warmup_started_at"] = datetime.now(timezone.utc) - timedelta(days=4)
    assert emailer.warmup_cap(raw) == 17
    raw["warmup_started_at"] = datetime.now(timezone.utc) - timedelta(days=30)
    assert emailer.warmup_cap(raw) == 30
    assert emailer.get_seat(s["id"])["warmup_completed"] is True
    assert "smtp_pass" not in emailer.list_seats()[0]


def test_unsubscribe_token_flow(clean, monkeypatch):
    lst = lists.create_list("L")
    (cid,) = _contacts_in_list(lst["id"], 1, email="u@acme.com")
    camp = campaigns.create_campaign(name="c", list_ids=[lst["id"]], is_manual=True, active=True,
                                     steps=[{"type": "visitProfile"}, {"type": "visitProfile"}])
    executor.tick(camp["id"], now=NOW)
    sid = lists.get_contact(cid)["campaign_status"][0]["id"]
    with get_conn() as conn:
        conn.execute("INSERT INTO sales_email_events (token, status_id, kind) VALUES ('tok', %s, 'sent')", (sid,))
    emailer.record_open("tok")
    assert emailer.unsubscribe("tok")
    c = lists.get_contact(cid)
    assert c["unsubscribed"] and emailer.is_suppressed("U@acme.com")
    assert {s["state"] for s in c["campaign_status"]} == {"skipped"}


def test_build_message_has_tracking_and_unsubscribe(clean):
    seat = {"email": "me@doers.studio", "name": "Saad", "track_opening": True, "remove_unsubscribe_link": False,
            "signature": "Saad\nDoers Studio"}
    msg, mid = emailer.build_message(seat, "a@b.com", "hi", "Line one\n\nLine two", "TOKEN", "<x@y>")
    text, html = (p.get_payload(decode=True).decode() for p in msg.get_payload())
    assert "/api/sales/t/u/TOKEN" in text and "Saad\nDoers Studio" in text
    assert "/api/sales/t/o/TOKEN.gif" in html and "/api/sales/t/u/TOKEN" in html
    assert msg["In-Reply-To"] == "<x@y>" and msg["List-Unsubscribe"] and mid.endswith("@doers.studio>")


# --------------------------------------------------------------- enrichment --

def test_enrich_email_pattern_with_mx(clean, monkeypatch):
    from sales import enrich

    (cid,) = _contacts_in_list(lists.create_list("L")["id"], 1, website="https://www.acme.com/")
    monkeypatch.setattr(enrich, "has_mx", lambda d: d == "acme.com")
    monkeypatch.delenv("HUNTER_API_KEY", raising=False)
    out = enrich.enrich_email(cid)
    assert out == {"email": "sara.ali@acme.com", "email_status": "mx_valid", "email_enriched": True}


def test_enrich_email_no_domain(clean, monkeypatch):
    from sales import enrich

    cid, _ = lists.upsert_contact({"full_name": "No Co", "profile_url": "https://www.linkedin.com/in/noco"})
    assert enrich.enrich_email(cid)["email_status"] == "not_found"
    assert enrich.enrich_phone(cid)["phone"] is None


# ---------------------------------------------------------------- directory --

def test_directory_search_masks_and_reveal_imports(clean):
    src = lists.create_list("src")
    ids = _contacts_in_list(src["id"], 3)
    lists.update_contact(ids[0], {"location": "Sydney, Australia", "industry": "Software"})
    lists.update_contact(ids[1], {"location": "Lahore, Pakistan"})
    assert directory.search_leads()["note"] == "at least one filter is required"
    r = directory.search_leads(job_title=["CEO"], location=["Australia"])
    assert r["total"] == 1
    item = r["items"][0]
    assert set(item) == {"id", "first_name", "job_title", "location", "industry", "source"}
    dst = lists.create_list("dst")
    out = directory.reveal_leads([item["id"]], dst["id"])
    assert out["imported"] == 1 and out["leads"][0]["profile_url"].endswith("/s0")
    assert directory.search_leads(job_title="CEO", exclude_list_id=dst["id"])["total"] == 2


def test_contact_upsert_dedupes_by_url_and_email(clean):
    a, new = lists.upsert_contact({"full_name": "A B", "profile_url": "linkedin.com/in/ab/"})
    b, new2 = lists.upsert_contact({"full_name": "A", "profile_url": "https://www.linkedin.com/in/ab"})
    assert new and not new2 and a == b
    c, _ = lists.upsert_contact({"full_name": "E Mail", "email": "x@y.com"})
    d, new3 = lists.upsert_contact({"full_name": "E", "email": "X@Y.com"})
    assert c == d and not new3
    assert lists.get_contact(a)["first_name"] == "A" and lists.get_contact(a)["last_name"] == "B"


def test_csv_import(clean):
    lst = lists.create_list("L")
    text = "First Name,Last Name,Company,Email,LinkedIn\nAli,Raza,Acme,ali@acme.com,\n,,,,\nBo,Li,Zeta,,linkedin.com/in/boli\n"
    r = lists.import_csv(lst["id"], text)
    assert r["created"] == 2 and r["skipped"] == 1
    assert lists.get_list(lst["id"])["contact_count"] == 2
