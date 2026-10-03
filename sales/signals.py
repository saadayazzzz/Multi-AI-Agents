"""Signal implementations: one function per Gojiberry signal type.

Each signal turns one agent variable into raw candidates (people), without
filtering or scoring - sales/runner.py does that uniformly afterwards:

    {"full_name", "profile_url", "headline", "job_title", "company",
     "company_url", "website", "location", "connection_degree",
     "intent_type", "intent", "intent_url", "intent_at", "signal_value"}

LinkedIn-backed signals read through the seat's own logged-in session
(sales/linkedin.py). Company-level signals (funding, hiring, technology)
come from live web search (agents.llm.research - Tavily or Gemini
grounding), then find the decision-makers at each company. Nothing here
invents a person: every candidate carries a real linkedin.com/in URL that a
page or search actually returned.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from sales import linkedin as li

Candidate = dict[str, Any]

_IN_URL = re.compile(r"^https?://([a-z]{2,3}\.)?linkedin\.com/in/[^/?#]+", re.I)
_HEADLINE_SPLIT = re.compile(r"\s+(?:@|at|\||·|-|–|,)\s+", re.I)


class SignalUnavailable(RuntimeError):
    """The signal can't run in this setup (e.g. needs a LinkedIn session)."""


def parse_headline(headline: str | None) -> tuple[str | None, str | None]:
    """'Founder @ Acme | building X' -> ('Founder', 'Acme')."""
    if not headline:
        return None, None
    first = headline.split("|")[0].strip()
    parts = _HEADLINE_SPLIT.split(first, maxsplit=1)
    if len(parts) == 2:
        return parts[0].strip() or None, parts[1].strip() or None
    return first or None, None


def _cand(p: dict, intent_type: str, value: str, intent: str | None = None,
          intent_url: str | None = None, intent_at: str | None = None) -> Candidate | None:
    url = (p.get("profile_url") or "").split("?")[0].rstrip("/")
    if not _IN_URL.match(url):
        return None
    title, company = parse_headline(p.get("headline"))
    return {
        "full_name": p.get("full_name") or p.get("author"),
        "profile_url": url,
        "headline": p.get("headline"),
        "job_title": p.get("job_title") or title,
        "company": p.get("company") or company,
        "company_url": p.get("company_url"),
        "website": p.get("website"),
        "location": p.get("location"),
        "connection_degree": p.get("connection_degree"),
        "open_to_work": bool(p.get("open_to_work")) or "open to work" in (p.get("headline") or "").lower(),
        "intent_type": intent_type,
        "intent": (intent or "")[:1500] or None,
        "intent_url": intent_url,
        "intent_at": intent_at,
        "signal_value": value,
    }


def _post_authors(posts: list[dict], intent_type: str, value: str, max_age_days: float) -> list[Candidate]:
    out = []
    for p in posts:
        if p.get("age_days") is not None and p["age_days"] > max_age_days:
            continue
        c = _cand(
            {**p, "full_name": p.get("author")}, intent_type, value,
            intent=f"Posted on LinkedIn: {p.get('text', '')[:1200]}",
            intent_url=p.get("post_url"), intent_at=p.get("posted_at"),
        )
        if c:
            out.append(c)
    return out


def _engagers(post_urls: list[str], seat: dict | None, intent_type: str, value: str,
              kinds: tuple[str, ...], per_post: int, label: str) -> list[Candidate]:
    out, seen = [], set()
    for url in post_urls:
        for kind in kinds:
            try:
                people = li.call("post_engagers", {"post_url": url, "kind": kind, "max": per_post}, seat)
            except li.LinkedInError:
                continue
            for p in people or []:
                verb = "commented on" if p.get("engagement") == "comment" else "reacted to"
                c = _cand(p, intent_type, value, intent=f"{verb.capitalize()} {label}: {url}", intent_url=url)
                if c and c["profile_url"] not in seen:
                    seen.add(c["profile_url"])
                    out.append(c)
    return out


def _require_session(seat: dict | None) -> None:
    if not li.has_session(seat):
        raise SignalUnavailable("needs a logged-in LinkedIn seat")


# ------------------------------------------------------------ keyword family --

def search_keyword(agent: dict, var: dict, seat: dict | None, limit: int) -> list[Candidate]:
    _require_session(seat)
    days = float(var.get("options", {}).get("max_age_days", 30))
    posts = li.call("search_posts", {"query": var["value"].strip('"'), "max": max(limit, 20)}, seat)
    return _post_authors(posts or [], var["type"], var["value"], days)


def search_keyword_engagers(kind: str) -> Callable:
    def run(agent: dict, var: dict, seat: dict | None, limit: int) -> list[Candidate]:
        _require_session(seat)
        posts = li.call("search_posts", {"query": var["value"].strip('"'), "max": 8}, seat) or []
        urls = [p["post_url"] for p in posts if p.get("post_url")][:4]
        return _engagers(urls, seat, var["type"], var["value"], (kind,), max(limit, 25),
                         f"a post about {var['value']}")
    return run


def event_keyword(agent: dict, var: dict, seat: dict | None, limit: int) -> list[Candidate]:
    _require_session(seat)
    out = []
    for ev in (li.call("search_events", {"query": var["value"].strip('"'), "max": 3}, seat) or [])[:3]:
        for p in li.call("event_attendees", {"url": ev["url"], "max": limit}, seat) or []:
            c = _cand(p, "EVENT_KEYWORD", var["value"],
                      intent=f"Attending/speaking at LinkedIn event '{ev.get('title')}'", intent_url=ev["url"])
            if c:
                out.append(c)
    return out


def group_keyword(agent: dict, var: dict, seat: dict | None, limit: int) -> list[Candidate]:
    _require_session(seat)
    out = []
    for g in (li.call("search_groups", {"query": var["value"].strip('"'), "max": 3}, seat) or [])[:2]:
        posts = li.call("group_posts", {"url": g["url"], "max": limit}, seat) or []
        for c in _post_authors(posts, "GROUP_KEYWORD", var["value"], 45):
            c["intent"] = f"Active in LinkedIn group '{g.get('title')}'. " + (c["intent"] or "")
            out.append(c)
    return out


# ----------------------------------------------------------- page engagement --

def page_engagers(label: str) -> Callable:
    def run(agent: dict, var: dict, seat: dict | None, limit: int) -> list[Candidate]:
        _require_session(seat)
        url = var["value"]
        if var["type"] == "YOUR_PROFILE":
            url = var.get("options", {}).get("url") or (seat or {}).get("profile_url")
            if not url:
                raise SignalUnavailable("set the seat's profile_url to use YOUR_PROFILE")
        posts = li.call("profile_posts", {"url": url, "max": 3}, seat) or []
        return _engagers([p["post_url"] for p in posts], seat, var["type"], var["value"],
                         ("comments", "reactions"), max(limit, 25), label)
    return run


def visited_profile(agent: dict, var: dict, seat: dict | None, limit: int) -> list[Candidate]:
    _require_session(seat)
    out = []
    for p in li.call("profile_views", {"max": max(limit, 30)}, seat) or []:
        c = _cand(p, "VISITED_PROFILE", var["value"], intent="Viewed your LinkedIn profile recently")
        if c:
            out.append(c)
    return out


def company_followers(agent: dict, var: dict, seat: dict | None, limit: int) -> list[Candidate]:
    _require_session(seat)
    out = []
    for p in li.call("company_followers", {"url": var["value"], "max": max(limit, 30)}, seat) or []:
        c = _cand(p, "YOUR_COMPANY_FOLLOWERS", var["value"], intent="Recently followed your company page")
        if c:
            out.append(c)
    return out


# --------------------------------------------------------- activity / job --

def recent_activity(agent: dict, var: dict, seat: dict | None, limit: int) -> list[Candidate]:
    """Gojiberry's highest-volume signal: ICP-role people posting right now,
    no topic requirement. First-person phrases keep LinkedIn's search to
    real posts instead of its mixed groups/events/suggestions results."""
    _require_session(seat)
    titles = [t for t in (agent.get("target_job_titles") or ["founder", "CEO"]) if t.strip()][:6]
    out = []
    for t in titles:
        posts = li.call("search_posts", {"query": f"as a {t}", "max": 30}, seat) or []
        for c in _post_authors(posts, "RECENT_ACTIVITY", "true", 14):
            c["intent"] = "Active on LinkedIn this week. " + (c["intent"] or "")
            out.append(c)
    return out


_NEW_JOB_QUERIES = ["starting a new position as {t}", "excited to join as {t}", "new role {t}"]


def recently_changed_job(agent: dict, var: dict, seat: dict | None, limit: int) -> list[Candidate]:
    _require_session(seat)
    titles = [t for t in (agent.get("target_job_titles") or ["founder"]) if t.strip()][:3]
    out = []
    for t in titles:
        for q in _NEW_JOB_QUERIES[:2]:
            posts = li.call("search_posts", {"query": q.format(t=t), "max": 15}, seat) or []
            for c in _post_authors(posts, "RECENTLY_CHANGED_JOB", "true", 90):
                c["intent"] = "Recently started a new role. " + (c["intent"] or "")
                out.append(c)
    return out


# ------------------------------------------------- company-level (web) --

_COMPANIES_SCHEMA = {
    "type": "object",
    "properties": {
        "companies": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "domain": {"type": ["string", "null"]},
                    "evidence": {"type": "string", "description": "what the source actually says"},
                    "date": {"type": ["string", "null"], "description": "YYYY-MM-DD if the source gives one"},
                    "round": {"type": ["string", "null"]},
                    "location": {"type": ["string", "null"]},
                    "industry": {"type": ["string", "null"]},
                    "source_url": {"type": ["string", "null"]},
                },
                "required": ["name", "domain", "evidence", "date", "round", "location", "industry", "source_url"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["companies"],
    "additionalProperties": False,
}

_WEB_SYS = (
    "You are a B2B sales researcher. Report only companies that the web search "
    "results actually name, with what the source says. Never invent a company, "
    "a date or a funding round - a short honest list beats a padded one."
)


def _web_companies(query: str, instruction: str, max_n: int = 8) -> list[dict]:
    from agents.llm import json_out, research

    notes = research(_WEB_SYS, query, max_tokens=4000)
    if not notes:
        return []
    data = json_out(_WEB_SYS, instruction + "\n\nSearch notes:\n" + notes, _COMPANIES_SCHEMA, max_tokens=4000)
    return (data.get("companies") or [])[:max_n]


_PEOPLE_SCHEMA = {
    "type": "object",
    "properties": {
        "people": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "full_name": {"type": "string"},
                    "job_title": {"type": "string"},
                    "profile_url": {"type": ["string", "null"]},
                },
                "required": ["full_name", "job_title", "profile_url"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["people"],
    "additionalProperties": False,
}


def people_at_company(company: str, titles: list[str], seat: dict | None, max_n: int = 3) -> list[dict]:
    """Decision-makers at a company: LinkedIn people search through the seat
    when available, else a web search that must return real /in/ URLs."""
    titles = [t for t in titles if t.strip()][:3] or ["Founder", "CEO"]
    found: list[dict] = []
    if li.has_session(seat):
        for t in titles:
            try:
                people = li.call("search_people", {"query": f"{t} {company}", "max": 5}, seat) or []
            except li.LinkedInError:
                continue
            for p in people:
                if company.lower().split()[0] in (p.get("headline") or "").lower():
                    found.append(p)
            if len(found) >= max_n:
                break
        return found[:max_n]
    from agents.llm import json_out, research

    notes = research(
        _WEB_SYS,
        f'site:linkedin.com/in "{company}" ({" OR ".join(titles)})',
        max_tokens=2500,
    )
    if not notes:
        return []
    data = json_out(
        _WEB_SYS,
        f"From these search notes, list people who currently work at {company} as one of: "
        f"{', '.join(titles)}. profile_url must be a linkedin.com/in URL that appears in the notes, "
        f"else null.\n\n{notes}",
        _PEOPLE_SCHEMA, max_tokens=1500,
    )
    return [p for p in data.get("people", []) if p.get("profile_url") and _IN_URL.match(p["profile_url"])][:max_n]


def _company_signal(agent: dict, var: dict, seat: dict | None, companies: list[dict],
                    intent_label: Callable[[dict], str]) -> list[Candidate]:
    from sales.lists import upsert_company

    out = []
    for co in companies[:6]:
        upsert_company({
            "name": co["name"], "domain": co.get("domain"), "industry": co.get("industry"),
            "headquarters": co.get("location"),
            "last_funding_at": co.get("date") if var["type"] == "RECENT_FUNDING_EVENT" and _is_date(co.get("date")) else None,
            "last_funding_round": co.get("round") if var["type"] == "RECENT_FUNDING_EVENT" else None,
            "is_hiring": True if var["type"] in ("HIRING", "TECHNOLOGY") else None,
            "technologies": [var["value"].lower()] if var["type"] == "TECHNOLOGY" else [],
        })
        for p in people_at_company(co["name"], agent.get("target_job_titles") or [], seat):
            c = _cand(
                {**p, "company": co["name"], "website": co.get("domain"), "location": p.get("location") or co.get("location")},
                var["type"], var["value"], intent=intent_label(co), intent_url=co.get("source_url"),
                intent_at=co.get("date") if _is_date(co.get("date")) else None,
            )
            if c:
                out.append(c)
    return out


def _is_date(s: str | None) -> bool:
    try:
        datetime.strptime(s or "", "%Y-%m-%d")
        return True
    except ValueError:
        return False


def _where(agent: dict) -> str:
    bits = []
    if agent.get("target_industries"):
        bits.append(" OR ".join(agent["target_industries"][:3]))
    if agent.get("target_locations"):
        bits.append(" OR ".join(agent["target_locations"][:3]))
    return " ".join(f"({b})" for b in bits)


def recent_funding(agent: dict, var: dict, seat: dict | None, limit: int) -> list[Candidate]:
    days = int(var.get("options", {}).get("days", 60))
    since = (datetime.now(timezone.utc) - timedelta(days=days)).date().isoformat()
    companies = _web_companies(
        f"startup raised funding seed OR \"series A\" OR \"series B\" {_where(agent)} after:{since}",
        f"List companies that announced a funding round on or after {since}. Drop anything older "
        f"or undated-and-unverifiable. Target: {_where(agent) or 'any industry'}.",
    )
    companies = [c for c in companies if not _is_date(c.get("date")) or c["date"] >= since]
    return _company_signal(
        agent, var, seat, companies,
        lambda co: f"{co['name']} raised {co.get('round') or 'funding'}"
                   f"{' on ' + co['date'] if co.get('date') else ''}: {co['evidence']}",
    )


def hiring(agent: dict, var: dict, seat: dict | None, limit: int) -> list[Candidate]:
    loc = (agent.get("target_locations") or [None])[0]
    companies: list[dict] = []
    if li.has_session(seat):
        try:
            jobs = li.call("search_jobs", {"query": var["value"].strip('"'), "location": loc, "max": 10}, seat) or []
            companies = [{"name": j["company"], "domain": None, "evidence": j.get("job_context", "")[:300],
                          "date": None, "round": None, "location": loc, "industry": None,
                          "source_url": j.get("company_url")} for j in jobs]
        except li.LinkedInError:
            companies = []
    if not companies:
        companies = _web_companies(
            f'hiring "{var["value"].strip(chr(34))}" job {_where(agent)}',
            f"List companies with an open job posting for '{var['value']}' in the last 30 days.",
        )
    return _company_signal(agent, var, seat, companies,
                           lambda co: f"{co['name']} is hiring for {var['value']}: {co['evidence']}")


def technology(agent: dict, var: dict, seat: dict | None, limit: int) -> list[Candidate]:
    tech = var["value"].strip('"')
    companies = _web_companies(
        f'job posting "{tech}" experience required {_where(agent)}',
        f"List companies whose recent job postings mention {tech} (a company that hires for a "
        f"technology, not a verified install base).",
    )
    return _company_signal(agent, var, seat, companies,
                           lambda co: f"{co['name']} hires for {tech} (seen in a job post): {co['evidence']}")


REGISTRY: dict[str, Callable[[dict, dict, dict | None, int], list[Candidate]]] = {
    "SEARCH_KEYWORD": search_keyword,
    "SEARCH_KEYWORD_POST": search_keyword,
    "SEARCH_KEYWORD_COMMENT": search_keyword_engagers("comments"),
    "SEARCH_KEYWORD_LIKE": search_keyword_engagers("reactions"),
    "EVENT_KEYWORD": event_keyword,
    "GROUP_KEYWORD": group_keyword,
    "COMPETITOR_PAGE_URL": page_engagers("a competitor's post"),
    "INFLUENCER_PAGE_URL": page_engagers("an influencer's post"),
    "YOUR_COMPANY": page_engagers("your company's post"),
    "YOUR_PROFILE": page_engagers("your post"),
    "VISITED_PROFILE": visited_profile,
    "YOUR_COMPANY_FOLLOWERS": company_followers,
    "RECENT_ACTIVITY": recent_activity,
    "RECENTLY_CHANGED_JOB": recently_changed_job,
    "RECENT_FUNDING_EVENT": recent_funding,
    "HIRING": hiring,
    "TECHNOLOGY": technology,
}
