"""Find leads from real, recent, PUBLIC LinkedIn activity - via web search only.

No LinkedIn scraping, no login, no automation of LinkedIn itself. This calls
research(), which runs a real web search (Tavily if configured, else Gemini's
own Google Search grounding) and asks it to surface publicly search-indexed
LinkedIn posts - the same URL/title/snippet a person would see googling
`site:linkedin.com "hiring is chaos"`. LinkedIn restricts how much of a post's
body search engines can index, so expect fewer, lower-volume results than a
generic company search - that's the tradeoff for the leads being about a real,
recent, verifiable signal instead of a cold guess.

IMPORTANT: recency claims ("posted 3 days ago") are exactly what an LLM
fabricates when it has no real search backing it. If research() has no live
web search (see agents/llm.py - this happens with an unconfigured/quota-zero
search backend), it silently answers from training data instead of erroring,
and would produce entirely invented people/companies/posts here. So this
module verifies every domain is real (as before) AND requires a real
linkedin.com URL for every candidate - if the model can't supply one, gap-fill
research() plausibly can't back the "recently active" claim.

Recency itself is verified from the URL, not the LLM's word. Every
linkedin.com/posts/... URL contains a numeric "activity" id, and LinkedIn
generates that id as a Snowflake-style value: its top 41 bits are the exact
post creation time in milliseconds since the Unix epoch (`id >> 22`). This is
public math on a public URL - not scraping, not login, not an LLM guess - and
it is far more reliable than hoping a search snippet happened to show a date
string. `_activity_id_date()` below decodes it; `posted_when` text-parsing is
now only the fallback for URLs that don't carry an activity id (e.g. a plain
profile URL).
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

import httpx
from dateutil import parser as date_parser

from agents.llm import json_out, research
from agents.reporter import report

MAX_AGE_DAYS = 15  # LinkedIn snippets rarely expose an exact date - a 7-day
# window verified almost nothing; 15 days keeps signals genuinely fresh
# (not the 5-months-old case this was built to catch) while actually yielding
# leads against what search engines index of LinkedIn.

MIN_ICP_FIT = 30  # a second, code-enforced line of defense on top of the
# prompt instructions below - catches the model scoring a competing agency/
# consultant's own marketing post low-but-nonzero instead of the intended 0.

_SYS = (
    "You are a B2B sales researcher for a solo builder who creates custom AI "
    "agents and automation systems for businesses. You find real, current "
    "buying signals - not just companies that fit a description. A signal is "
    "a specific, named founder or CEO who PUBLICLY posted on LinkedIn, within "
    "roughly the last 15 days, describing a manual/repetitive-work, scaling, "
    "understaffed-ops, or automation problem happening INSIDE THEIR OWN "
    "COMPANY, in their own voice, as something they themselves are living "
    "through right now.\n\n"
    "Explicitly EXCLUDE posts where the poster is an agency, consultant, "
    "freelancer, or automation/ops/AI-automation provider talking about this "
    "problem in general, or about 'a client of mine', or any other third "
    "party - that is their own marketing content, not a buying signal, and "
    "they are a competitor, not a prospect, even if the words match "
    "perfectly. A strong tell: the post reads like advice or a case study "
    "('I help businesses...', 'here's what I see with founders...', 'a "
    "client told me...') rather than a first-person account of their own "
    "company's actual situation right now. When unsure whether the pain is "
    "the poster's own or something they sell a fix for, treat it as the "
    "latter and exclude it - a shorter, genuinely-a-buyer list beats a "
    "longer list padded with other service providers.\n\n"
    "You have no LinkedIn login or API access - you "
    "only see what a public web search surfaces (the same URL, title, and "
    "snippet a person would get googling `site:linkedin.com`), so you can "
    "only report posts a search actually returned, never invent one. If a "
    "search turns up nothing recent and real, say so - a shorter, honest "
    "list beats a longer fabricated one.\n\n"
    "For each real result found in the search results given to you, report: "
    "the poster's name and role, their company name and website domain, the "
    "exact LinkedIn URL the search returned, how recent it is (exactly as "
    "shown in the result - '3d', '1 week ago', a date, whatever appeared - "
    "never invent a date that wasn't literally there), and what the post "
    "actually says in their own words (this becomes the opening line of a "
    "cold email, so keep it concrete and specific to them, not a generic "
    "paraphrase)."
)

_SCHEMA = {
    "type": "object",
    "properties": {
        "companies": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "company": {"type": "string"},
                    "domain": {"type": "string", "description": "bare domain, e.g. acme.com"},
                    "industry": {"type": "string"},
                    "icp_fit": {"type": "integer", "description": "0-100 fit"},
                    "contact_name": {
                        "type": ["string", "null"],
                        "description": "the poster's name, from the LinkedIn post/profile",
                    },
                    "contact_role": {
                        "type": ["string", "null"],
                        "description": "'CEO', 'Founder', 'Co-Founder', etc. - null if unclear",
                    },
                    "linkedin_url": {
                        "type": ["string", "null"],
                        "description": "the actual linkedin.com URL a search result returned "
                        "for this post/profile - null if none was found, NEVER guessed",
                    },
                    "posted_when": {
                        "type": ["string", "null"],
                        "description": "the ACTUAL date/relative-time marker exactly as the "
                        "search result showed it, e.g. '3 days ago', '1w', 'Jan 14', '2026-09-25'. "
                        "null if no such marker was visible - never a vague word like 'recent' "
                        "or 'recently', that's not a real timestamp and must be null instead",
                    },
                    "trigger": {
                        "type": "string",
                        "description": "the why-now hook, self-contained for a cold-email "
                        "opening line - mention it's from LinkedIn, include the WHEN from "
                        "posted_when if it's set (e.g. \"posted on LinkedIn 3 days ago that "
                        "they're...\"), otherwise just \"posted on LinkedIn that...\" (never "
                        "invent a timeframe posted_when doesn't have), plus what they actually "
                        "said in close to their own words",
                    },
                },
                "required": [
                    "company", "domain", "industry", "icp_fit",
                    "contact_name", "contact_role", "linkedin_url", "posted_when", "trigger",
                ],
                "additionalProperties": False,
            },
        }
    },
    "required": ["companies"],
    "additionalProperties": False,
}

_LINKEDIN_URL_RE = re.compile(r"^https://([a-z]{2,3}\.)?linkedin\.com/", re.IGNORECASE)
_ACTIVITY_ID_RE = re.compile(r"-activity-(\d+)")


def _activity_id_date(url: str) -> datetime | None:
    """Decode the real post timestamp out of a linkedin.com post URL's
    Snowflake-style activity id, if present. Ground truth, not a guess."""
    m = _ACTIVITY_ID_RE.search(url)
    if not m:
        return None
    try:
        ms = int(m.group(1)) >> 22
        dt = datetime.fromtimestamp(ms / 1000, tz=timezone.utc)
    except (ValueError, OverflowError, OSError):
        return None
    now = datetime.now(timezone.utc)
    if dt > now or dt.year < 2010:
        return None
    return dt


_RELATIVE_RE = re.compile(
    r"(\d+)\s*(h(?:our)?|d(?:ay)?|w(?:eek)?|mo(?:nth)?|y(?:ear)?)s?\b", re.IGNORECASE
)
_UNIT_DAYS = {"h": 1 / 24, "d": 1, "w": 7, "mo": 30, "y": 365}


def _days_ago(when: str | None) -> float | None:
    """Best-effort age in days from a search snippet's date text - handles
    both relative ('3 days ago', '1w') and absolute ('Jan 14', '2026-09-20')
    forms. Returns None if it can't be parsed at all - that's a real signal
    (a claim we can't verify), not a bug to paper over."""
    if not when:
        return None
    when = when.strip()
    if when.lower() in {"today", "just now", "now"}:
        return 0.0
    if when.lower() == "yesterday":
        return 1.0

    m = _RELATIVE_RE.search(when.lower())
    if m:
        qty, unit = float(m.group(1)), m.group(2)[:2] if m.group(2).startswith("mo") else m.group(2)[0]
        return qty * _UNIT_DAYS.get(unit, 1)

    try:
        parsed = date_parser.parse(when, fuzzy=True, default=datetime.now(timezone.utc))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        delta = datetime.now(timezone.utc) - parsed
        # a future "date" is a parse artifact (fuzzy parsing grabbed a stray
        # number as a day/year) - not usable evidence either way
        return delta.total_seconds() / 86400 if delta >= timedelta(0) else None
    except (ValueError, OverflowError):
        return None


def _domain_is_real(domain: str) -> bool:
    """A cheap but critical trust check: the model can and does invent
    plausible-sounding companies/domains even when given real search
    results - never let a fabricated company reach a sales pipeline."""
    for scheme in ("https://", "http://"):
        try:
            r = httpx.head(
                f"{scheme}{domain}", timeout=8, follow_redirects=True,
            )
            if r.status_code < 500:
                return True
        except Exception:  # noqa: BLE001 - try the next scheme
            continue
    return False


# Short, keyword-style queries - not instructional paragraphs. research()'s
# Tavily path searches the `user` argument VERBATIM (truncated to 400 chars),
# so a long paragraph of instructions burns that budget on prose instead of
# search terms and gets Tavily little to nothing back. Split across a few
# focused queries instead of one crammed one - real search engines, same as
# a human trying several searches, not one giant query.
_QUERY_GROUPS = [
    '"hiring is chaos" OR "doing this manually" OR "drowning in spreadsheets"',
    '"scaling too fast" OR "need to automate" OR "understaffed" OR "manual process"',
    '"need to automate" OR "manual work" OR "repetitive tasks" OR "AI agent"',
    '"solo founder" OR "wearing every hat" OR "systems over hustle" OR "ops chaos"',
]


# Plain keyword phrases for LinkedIn's own search UI (used by the scrape
# path below) - its search doesn't reliably honour boolean OR the way a web
# search engine does, so these are kept as simple phrases, one query each.
_SCRAPE_QUERIES = [
    "founder hiring is chaos",
    "CEO drowning in spreadsheets manual",
    "founder need to automate manual process",
    "solo founder wearing every hat systems",
    "startup founder scaling too fast understaffed",
    "CEO manual work repetitive tasks AI agent",
    "founder operations chaos no systems",
    "small business owner overwhelmed manual processes",
    "founder building in public startup",
    "CEO systems over hustle productivity",
    "startup founder ai agents automation",
    "founder no-code manual workflow",
]


def _find_via_scrape(icp: str, n: int, exclude: set[str]) -> list[dict]:
    """The real-time path: search LinkedIn's own UI (sorted by Latest) via
    the user's logged-in session - see linkedin_scrape.py for why this is
    used at all despite the ToS risk, and why it solves recency better than
    a public search index ever can (LinkedIn's own UI exposes an exact
    timestamp for content only a logged-in viewer can rank as newest)."""
    from concurrent.futures import ThreadPoolExecutor, as_completed

    from outreach import linkedin_scrape as scrape

    # Each query spawns its own headless Chrome via a subprocess.run() call
    # (which releases the GIL while waiting), so running them concurrently
    # turns ~8 sequential 30-90s searches into one ~30-90s batch instead of
    # 5-8 minutes end to end. Capped at 4 at once - more than that both
    # strains this machine and looks more bot-like to LinkedIn in a burst.
    posts, seen = [], set()
    with ThreadPoolExecutor(max_workers=6) as pool:
        futures = {pool.submit(scrape.search_recent_posts, q, 15): q for q in _SCRAPE_QUERIES}
        for fut in as_completed(futures):
            q = futures[fut]
            try:
                results = fut.result()
            except Exception as e:  # noqa: BLE001 - one slow/failed query shouldn't sink the batch
                report(f"  LinkedIn search for '{q}' failed ({e}) - skipping", kind="status")
                continue
            for p in results:
                if p["post_url"] in seen:
                    continue
                seen.add(p["post_url"])
                if p.get("age_days") is not None and p["age_days"] <= MAX_AGE_DAYS:
                    posts.append(p)
    if not posts:
        return []

    notes = "\n\n---\n\n".join(
        f"Author: {p['author']}\nProfile: {p.get('profile_url') or ''}\n"
        f"Post URL: {p['post_url']}\nPosted: {p['age_days']} days ago\n"
        f"Text: {p['text']}"
        for p in posts
    )
    data = json_out(
        _SYS,
        f"Extract ONLY people/companies explicitly named in the notes below - "
        f"do not invent or infer anything not literally mentioned there. Score "
        f"icp_fit against this target profile (0 if it's a poor match, and "
        f"ALSO 0 if the poster is themselves an agency/consultant/automation "
        f"provider describing the problem generically or via a client's "
        f"story rather than their own company's real situation - see system "
        f"prompt): {icp}\n\n"
        f"For linkedin_url use the exact 'Post URL' given for that person. For "
        f"posted_when use the exact 'Posted' value given, verbatim.\n\n" + notes,
        _SCHEMA,
        max_tokens=7000,
    )
    out: list[dict] = []
    dropped_bad_domain = 0
    dropped_low_fit = 0
    for c in data["companies"]:
        dom = c["domain"].lower().strip().replace("https://", "").replace("http://", "")
        dom = dom.replace("www.", "").strip("/")
        if not dom or dom in exclude or dom in {o["domain"] for o in out}:
            continue
        url = (c.get("linkedin_url") or "").strip()
        if not url or not _LINKEDIN_URL_RE.match(url):
            continue
        if (c.get("icp_fit") or 0) < MIN_ICP_FIT:
            dropped_low_fit += 1
            continue
        if not _domain_is_real(dom):
            dropped_bad_domain += 1
            continue
        out.append({**c, "domain": dom, "linkedin_url": url})
        if len(out) >= n:
            break
    if dropped_low_fit:
        report(
            f"  dropped {dropped_low_fit} low icp_fit (likely other service "
            f"providers pitching, not real buyers) - live LinkedIn search path",
            kind="status",
        )
    if dropped_bad_domain:
        report(
            f"  dropped {dropped_bad_domain} unverifiable/fabricated companies "
            f"(live LinkedIn search path)",
            kind="status",
        )
    return out


_ACTIVE_SYS = (
    "You are a B2B sales researcher. You extract real people from LinkedIn "
    "search notes who PUBLICLY posted within the last two weeks and whose "
    "role/company matches the target profile. Unlike a pain-point search, "
    "this one does NOT require the post to be about any specific problem - "
    "the signal here is simply 'this real person, matching the ICP, is "
    "currently active on LinkedIn', the same 'Top 5% most active profiles' "
    "signal a tool like Gojiberry uses: no topic requirement, just a real, "
    "recent, role-matching post. Only report people a search actually "
    "returned, never invent one - a shorter, honest list beats a longer "
    "fabricated one. Still exclude agencies/consultants/service providers "
    "pitching their own services rather than running their own company."
)


def find_active_profiles(
    job_titles: list[str], icp: str, n: int = 10, exclude: set[str] | None = None,
) -> list[dict]:
    """The bulk-volume signal real Gojiberry agent logs show produces the
    overwhelming majority of their leads (189 in a single run, per their
    own get_agent_logs) - NOT their keyword-search signal (which, like
    ours, only yields 0-1 per run). The difference: this doesn't require a
    post to be ABOUT anything in particular, just that a real person
    matching the ICP by role is genuinely, recently active on LinkedIn.
    Same verification bar as find_leads (real domain, real decoded/
    LinkedIn-displayed recency, no fabrication) - just not gated on a
    specific pain-point phrase."""
    from concurrent.futures import ThreadPoolExecutor, as_completed

    from outreach import linkedin_scrape as scrape

    exclude = exclude or set()
    titles = job_titles or ["founder", "CEO"]
    # Bare single-word queries ("Founder") pull in LinkedIn's noisy mixed
    # results (groups, events, "people also viewed") that aren't posts at
    # all; wrapping each title in a few generic first-person phrases keeps
    # results to actual post content without requiring any specific
    # pain-point topic.
    queries = []
    for t in titles[:4]:
        t = t.strip()
        if not t:
            continue
        queries.append(f"as a {t}")
    queries = list(dict.fromkeys(queries))[:8] or ["as a founder", "building my company"]

    posts, seen = [], set()
    with ThreadPoolExecutor(max_workers=6) as pool:
        futures = {pool.submit(scrape.search_recent_posts, q, 20): q for q in queries}
        for fut in as_completed(futures):
            q = futures[fut]
            try:
                results = fut.result()
            except Exception as e:  # noqa: BLE001
                report(f"  active-profile search for '{q}' failed ({e}) - skipping", kind="status")
                continue
            for p in results:
                if p["post_url"] in seen:
                    continue
                seen.add(p["post_url"])
                if p.get("age_days") is not None and p["age_days"] <= MAX_AGE_DAYS:
                    posts.append(p)
    if not posts:
        return []

    notes = "\n\n---\n\n".join(
        f"Author: {p['author']}\nProfile: {p.get('profile_url') or ''}\n"
        f"Post URL: {p['post_url']}\nPosted: {p['age_days']} days ago\n"
        f"Text: {p['text']}"
        for p in posts
    )
    data = json_out(
        _ACTIVE_SYS,
        f"Extract ONLY people/companies explicitly named in the notes below. "
        f"Score icp_fit purely on role/industry/location match against this "
        f"target profile (0 if it's a poor match, or if the poster is "
        f"themselves an agency/consultant pitching their own services): "
        f"{icp}\n\nFor linkedin_url use the exact 'Post URL' given. For "
        f"posted_when use the exact 'Posted' value given, verbatim. For "
        f"trigger, just note they're actively posting on LinkedIn - no need "
        f"to force a pain-point connection.\n\n" + notes,
        _SCHEMA,
        max_tokens=7000,
    )
    out: list[dict] = []
    dropped_bad_domain = 0
    dropped_low_fit = 0
    for c in data["companies"]:
        dom = c["domain"].lower().strip().replace("https://", "").replace("http://", "")
        dom = dom.replace("www.", "").strip("/")
        if not dom or dom in exclude or dom in {o["domain"] for o in out}:
            continue
        url = (c.get("linkedin_url") or "").strip()
        if not url or not _LINKEDIN_URL_RE.match(url):
            continue
        if (c.get("icp_fit") or 0) < MIN_ICP_FIT:
            dropped_low_fit += 1
            continue
        if not _domain_is_real(dom):
            dropped_bad_domain += 1
            continue
        out.append({**c, "domain": dom, "linkedin_url": url})
        if len(out) >= n:
            break
    if dropped_low_fit:
        report(f"  dropped {dropped_low_fit} low icp_fit - active-profile search", kind="status")
    if dropped_bad_domain:
        report(f"  dropped {dropped_bad_domain} unverifiable companies - active-profile search", kind="status")
    return out


def find_leads(icp: str, n: int = 10, exclude: set[str] | None = None) -> list[dict]:
    exclude = exclude or set()

    from outreach import linkedin_scrape as scrape

    if scrape.has_session():
        try:
            leads = _find_via_scrape(icp, n, exclude)
            if leads:
                report(
                    f"  found {len(leads)} via live LinkedIn session search "
                    f"(real timestamps, sorted by Latest)",
                    kind="status",
                )
                return leads
            report(
                "  live LinkedIn session search found nothing within the "
                f"{MAX_AGE_DAYS}-day window - falling back to public search index",
                kind="status",
            )
        except Exception as e:  # noqa: BLE001 - never let this crash the cycle
            report(
                f"  live LinkedIn session search failed ({e}) - falling back "
                f"to public search index",
                kind="status",
            )

    all_notes = []
    for group in _QUERY_GROUPS:
        query = f"site:linkedin.com/posts (CEO OR founder) ({group})"
        chunk = research(_SYS, query, max_tokens=4000)
        if chunk:
            all_notes.append(chunk)
    notes = "\n\n---\n\n".join(all_notes)
    data = (
        json_out(
            _SYS,
            f"Extract ONLY people/companies explicitly named in the notes below - "
            f"do not invent or infer anything not literally mentioned there. Score "
            f"icp_fit against this target profile (0 if it's a poor match - a real "
            f"person's post that doesn't fit the profile is still real, just low-"
            f"fit, not something to invent around; ALSO 0 if the poster is "
            f"themselves an agency/consultant/automation provider describing the "
            f"problem generically or via a client's story rather than their own "
            f"company's real situation - see system prompt): {icp}\n\n"
            f"Drop anything without both a real domain and a real linkedin.com "
            f"URL. For posted_when: only a literal date or relative-time marker "
            f"from the notes counts - if the notes only say something vague like "
            f"'recently' with no actual marker, posted_when must be null, not "
            f"that word.\n\n" + notes,
            _SCHEMA,
            max_tokens=7000,
        )
        if notes
        else {"companies": []}
    )
    out: list[dict] = []
    dropped_no_source = 0
    dropped_bad_domain = 0
    dropped_stale = 0
    dropped_no_date = 0
    dropped_low_fit = 0
    for c in data["companies"]:
        dom = c["domain"].lower().strip().replace("https://", "").replace("http://", "")
        dom = dom.replace("www.", "").strip("/")
        if not dom or dom in exclude or dom in {o["domain"] for o in out}:
            continue
        url = (c.get("linkedin_url") or "").strip()
        if not url or not _LINKEDIN_URL_RE.match(url):
            # No verifiable public post behind this claim - exactly the kind
            # of thing a search-less model fabricates. Skip rather than trust it.
            dropped_no_source += 1
            continue
        # The actual recency enforcement - not just "looks like a date", but
        # genuinely within MAX_AGE_DAYS. A lead whose post is months old is
        # a dead opportunity (someone else likely already responded to it),
        # so this is a hard drop, not a confidence flag.
        # Ground truth first: the real timestamp encoded in the post URL
        # itself. Only fall back to the LLM's transcription of a date string
        # (unreliable - it depends on the search snippet happening to show
        # one) when the URL doesn't carry a decodable activity id.
        real_date = _activity_id_date(url)
        if real_date is not None:
            age = (datetime.now(timezone.utc) - real_date).total_seconds() / 86400
            posted_when = f"{int(age)}d ago ({real_date.date().isoformat()})"
        else:
            age = _days_ago(c.get("posted_when"))
            posted_when = c.get("posted_when")
        if age is None:
            dropped_no_date += 1
            continue
        if age > MAX_AGE_DAYS:
            dropped_stale += 1
            continue
        if (c.get("icp_fit") or 0) < MIN_ICP_FIT:
            dropped_low_fit += 1
            continue
        if not _domain_is_real(dom):
            dropped_bad_domain += 1
            continue
        out.append({**c, "domain": dom, "linkedin_url": url, "posted_when": posted_when})
        if len(out) >= n:
            break
    if dropped_low_fit:
        report(
            f"  dropped {dropped_low_fit} low icp_fit (likely other service "
            f"providers pitching, not real buyers)",
            kind="status",
        )
    if dropped_no_source:
        report(
            f"  dropped {dropped_no_source} without a real LinkedIn source "
            f"(no linkedin.com URL in the search results - likely fabricated)",
            kind="status",
        )
    if dropped_no_date:
        report(
            f"  dropped {dropped_no_date} with no verifiable post date "
            f"(can't confirm they're active in the last {MAX_AGE_DAYS} days)",
            kind="status",
        )
    if dropped_stale:
        report(f"  dropped {dropped_stale} whose post is older than {MAX_AGE_DAYS} days", kind="status")
    if dropped_bad_domain:
        report(f"  dropped {dropped_bad_domain} unverifiable/fabricated companies", kind="status")
    return out[:n]
