"""Enums and value normalisation, matching Gojiberry's own field values."""
from __future__ import annotations

import re

COMPANY_SIZES = ["2-10", "11-50", "51-200", "201-500", "501-1000", "1001-5000", "5001-10000", "10001+"]

COMPANY_TYPES = [
    "All company types", "Private Company", "Public Company", "Startup",
    "Non-profit", "Government", "Educational Institution", "Other",
]

AGENT_TYPES = ["autopilot", "lookalike", "website-visitor"]

# type -> (base intent strength 0-1, needs a LinkedIn session, description)
SIGNALS: dict[str, tuple[float, bool, str]] = {
    "SEARCH_KEYWORD":         (0.85, True,  "People who recently posted about a keyword"),
    "SEARCH_KEYWORD_POST":    (0.85, True,  "Authors of recent posts matching a keyword"),
    "SEARCH_KEYWORD_COMMENT": (0.75, True,  "People commenting on recent posts about a keyword"),
    "SEARCH_KEYWORD_LIKE":    (0.55, True,  "People reacting to recent posts about a keyword"),
    "EVENT_KEYWORD":          (0.70, True,  "Attendees / speakers of LinkedIn events matching a keyword"),
    "GROUP_KEYWORD":          (0.50, True,  "Active members of LinkedIn groups matching a keyword"),
    "COMPETITOR_PAGE_URL":    (0.80, True,  "People engaging with a competitor's page posts"),
    "INFLUENCER_PAGE_URL":    (0.60, True,  "People engaging with an influencer's posts"),
    "YOUR_COMPANY":           (0.90, True,  "People engaging with your company page posts"),
    "YOUR_PROFILE":           (0.90, True,  "People engaging with your own posts"),
    "VISITED_PROFILE":        (0.90, True,  "People who viewed your LinkedIn profile"),
    "YOUR_COMPANY_FOLLOWERS": (0.70, True,  "New followers of your company page (admin only)"),
    "RECENT_ACTIVITY":        (0.50, True,  "ICP-matching people active on LinkedIn right now"),
    "RECENTLY_CHANGED_JOB":   (0.80, True,  "ICP-matching people who just started a new role"),
    "RECENT_FUNDING_EVENT":   (0.80, False, "Decision-makers at companies that just raised"),
    "HIRING":                 (0.70, False, "Decision-makers at companies hiring for a role/keyword"),
    "TECHNOLOGY":             (0.60, False, "Companies hiring for a technology (seen in job posts)"),
}

# Gojiberry rejects these on create_agent; we accept the same set.
FORBIDDEN_SIGNALS = {"LOOKALIKE", "JOB_SEARCH"}
# Signals whose `value` is a flag rather than a search term.
FLAG_SIGNALS = {
    "RECENT_ACTIVITY", "RECENTLY_CHANGED_JOB", "RECENT_FUNDING_EVENT",
    "YOUR_PROFILE", "VISITED_PROFILE",
}

LINKEDIN_STEPS = {"invitation", "invitationNote", "message", "voiceMessage", "visitProfile", "likePosts"}
STEP_TYPES = LINKEDIN_STEPS | {"email"}
INVITATION_STEPS = {"invitation", "invitationNote"}
REPLY_TYPES = {"message", "voiceMessage", "email"}

INVITE_NOTE_MAX = 180
INVITE_NOTE_MAX_SALES_NAV = 280
LINKEDIN_MESSAGE_MAX = 1900

_SIZE_RE = re.compile(r"(\d[\d,]*)\s*(?:-|to|–)\s*(\d[\d,]*)|(\d[\d,]*)\s*\+")


def normalize_company_size(v: str) -> str | None:
    """'1-10 employees' / '11 to 50' / '10,000+' -> Gojiberry bracket."""
    if v in COMPANY_SIZES:
        return v
    m = _SIZE_RE.search(v or "")
    if not m:
        return None
    if m.group(3):
        lo = int(m.group(3).replace(",", ""))
        return "10001+" if lo >= 10000 else None
    return size_from_headcount(int(m.group(2).replace(",", "")))


def size_from_headcount(n: int | None) -> str | None:
    if n is None:
        return None
    for b in COMPANY_SIZES[:-1]:
        a, z = (int(x) for x in b.split("-"))
        if n <= z:
            return b
    return "10001+"
