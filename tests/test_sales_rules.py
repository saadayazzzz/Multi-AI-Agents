"""Pure rules: step validation, value normalisation, scheduling, scoring maths."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from sales.agents import AgentError, validate_variables
from sales.campaigns import CampaignError, validate_steps
from sales.constants import normalize_company_size
from sales.enrich import patterns
from sales.executor import schedule_after
from sales.scoring import heuristic_persona, intent_score
from sales.signals import parse_headline
from sales.writer import render, split_paragraphs


def test_steps_assign_numbers_ids_and_defaults():
    steps = validate_steps([{"type": "invitation"}, {"type": "message"}, {"type": "email", "message": "Hi [FirstName]", "subject": "s"}])
    assert [s["step_number"] for s in steps] == [0, 1, 2]
    assert all(s["id"] for s in steps)
    assert steps[0]["delay_after_last_step"] == 2
    assert steps[1]["message_mode"] == "ai"  # no content -> ai
    assert steps[2]["message_mode"] == "same"  # content -> same


@pytest.mark.parametrize("steps, msg", [
    ([{"type": "invitation"}, {"type": "invitationNote", "note": "x"}], "only one connection request"),
    ([{"type": "message"}, {"type": "invitation"}], "can't come after a message"),
    ([{"type": "voiceMessage", "url": "u"}, {"type": "invitation"}], "can't come after a message"),
    ([{"type": "message", "delay_after_last_step": 0}], ">= 1"),
    ([{"type": "message", "delayAfterLastStep": 1.5}], ">= 1"),
    ([{"type": "invitationNote"}], "needs a note"),
    ([{"type": "invitationNote", "note": "x" * 181}], "max 180"),
    ([{"type": "message", "message_mode": "same"}], "needs the message text"),
    ([{"type": "message", "message": "x" * 1901}], "max 1900"),
    ([{"type": "email", "message": "body"}], "needs a subject"),
    ([{"type": "voiceMessage"}], "audio url"),
    ([{"type": "likePosts", "numberOfPosts": 4}], "1-3"),
    ([{"type": "tweet"}], "unknown type"),
    ([], "at least one step"),
])
def test_step_rules(steps, msg):
    with pytest.raises(CampaignError, match=msg):
        validate_steps(steps)


def test_sales_navigator_note_limit():
    validate_steps([{"type": "invitationNote", "note": "x" * 250}], sales_navigator=True)
    with pytest.raises(CampaignError):
        validate_steps([{"type": "invitationNote", "note": "x" * 281}], sales_navigator=True)


def test_camel_case_keys_accepted():
    s = validate_steps([{"type": "invitation", "likePostsBeforeInvitation": True, "delayAfterLastStep": 3},
                        {"type": "likePosts", "numberOfPosts": 2}])
    assert s[0]["like_posts_before_invitation"] is True and s[0]["delay_after_last_step"] == 3
    assert s[1]["number_of_posts"] == 2


def test_variables_rules():
    four = [{"type": "SEARCH_KEYWORD", "value": f"k{i}"} for i in range(4)]
    assert len(validate_variables(four)) == 4
    with pytest.raises(AgentError, match="4-15"):
        validate_variables(four[:3])
    with pytest.raises(AgentError, match="not allowed"):
        validate_variables(four[:3] + [{"type": "LOOKALIKE", "value": "x"}])
    with pytest.raises(AgentError, match="LinkedIn page URL"):
        validate_variables(four[:3] + [{"type": "COMPETITOR_PAGE_URL", "value": "acme.com"}])
    with pytest.raises(AgentError, match="only used by autopilot"):
        validate_variables(four, agent_type="lookalike")
    assert validate_variables([], "autopilot") == []


@pytest.mark.parametrize("raw, want", [
    ("1-10 employees", "2-10"), ("11-50 employees", "11-50"), ("51-200", "51-200"),
    ("201 to 500", "201-500"), ("10,000+", "10001+"), ("10001+", "10001+"), ("lots", None),
])
def test_company_size(raw, want):
    assert normalize_company_size(raw) == want


def test_parse_headline():
    assert parse_headline("Founder @ Acme | AI agents") == ("Founder", "Acme")
    assert parse_headline("CEO at Big Co") == ("CEO", "Big Co")
    assert parse_headline("Co-Founder - Zeta") == ("Co-Founder", "Zeta")
    assert parse_headline("Head of Product") == ("Head of Product", None)


def test_render_and_split():
    c = {"first_name": "Sara", "last_name": "Ali", "company": "Acme"}
    assert render("Hi [FirstName] [lastname] at [COMPANY]", c) == "Hi Sara Ali at Acme"
    assert render("Hi [FirstName]", {}) == "Hi there"
    assert split_paragraphs("a\n\nb\n \nc") == ["a", "b", "c"]


def test_schedule_after_skips_weekend_and_sets_launch_hour():
    tz = ZoneInfo("UTC")
    fri = datetime(2026, 10, 2, 15, 30, tzinfo=timezone.utc)  # Friday
    due = schedule_after(fri, 1, [1, 2, 3, 4, 5], 9, tz)
    assert due == datetime(2026, 10, 5, 9, 0, tzinfo=timezone.utc)  # Monday 9:00
    assert schedule_after(fri, 3, [1, 2, 3, 4, 5, 6, 7], 10, tz).date() == date(2026, 10, 5)


def test_schedule_after_respects_timezone():
    due = schedule_after(datetime(2026, 10, 5, 12, tzinfo=timezone.utc), 1, [1, 2, 3, 4, 5], 9, ZoneInfo("Asia/Karachi"))
    assert due == datetime(2026, 10, 6, 4, 0, tzinfo=timezone.utc)  # 09:00 PKT


def test_intent_score_decays_with_age():
    now = datetime(2026, 10, 2, tzinfo=timezone.utc)
    fresh = intent_score({"intent_type": "VISITED_PROFILE", "intent_at": now.isoformat()}, now)
    old = intent_score({"intent_type": "VISITED_PROFILE", "intent_at": (now - timedelta(days=30)).isoformat()}, now)
    undated = intent_score({"intent_type": "VISITED_PROFILE"}, now)
    assert fresh == 0.9 and old == 0.45 and undated == 0.72
    assert intent_score({"intent_type": "RECENT_ACTIVITY", "intent_at": now.isoformat()}, now) < fresh


def test_heuristic_persona():
    assert heuristic_persona({"job_title": "Founder & CEO"}, ["CEO"]) == 1.0
    assert heuristic_persona({"headline": "Marketing intern"}, ["CEO"]) == 0.2
    assert heuristic_persona({"headline": "Head of Growth"}, ["Head of Product"]) > 0.2


def test_email_patterns():
    assert patterns("José", "Núñez", "acme.com")[0] == "jose.nunez@acme.com"
    assert patterns("Ali", "", "acme.com") == ["ali@acme.com"]
    assert patterns("", "X", "acme.com") == []
