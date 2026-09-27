"""Generate the cold email + two follow-ups, personalised with the visibility finding."""
from __future__ import annotations

from typing import Any

from agents.llm import json_out

_SYS = (
    "You write short, specific, non-salesy B2B cold emails that get replies. No "
    "hype, no jargon, no fake flattery. One concrete hook, one clear ask."
)

_SCHEMA = {
    "type": "object",
    "properties": {
        "subject": {"type": "string"},
        "body": {"type": "string"},
        "followup_1": {"type": "string"},
        "followup_2": {"type": "string"},
    },
    "required": ["subject", "body", "followup_1", "followup_2"],
    "additionalProperties": False,
}


def compose(lead: dict[str, Any], campaign: dict[str, Any]) -> dict[str, str]:
    from_name = campaign.get("from_name") or "Saad"
    geo_line = (
        f"Also ran a quick AI-search visibility check on them: {lead['geo_finding']} - "
        f"usable as a secondary credibility point, NOT the opening line."
        if lead.get("geo_finding") else
        "No visibility check run - ignore this angle entirely."
    )
    prompt = f"""\
SENDER: {from_name}
OFFER (what the sender does): {campaign['offer']}

PROSPECT
  company: {lead['company']}  ({lead['domain']})
  contact: {lead.get('contact_name') or 'there'} — {lead.get('contact_role') or 'Founder'}
  why now (THE opening hook): {lead.get('trigger') or 'n/a'}
  {geo_line}

Write:
- subject: <= 6 words, lowercase, specific, no clickbait
- body: <= 110 words. Open with the why-now trigger (concrete, specific to
  THEM, not generic). One or two sentences on what you'd actually build for
  them. Optionally, ONE short line weaving in the visibility finding as a
  bonus "by the way" data point if it's set. Ask for a 15-min call OR "want a
  quick breakdown of what I'd build?". Sign as {from_name}. Final line
  exactly: "Not relevant? Reply 'unsubscribe' and I'll stop."
- followup_1: <= 45 words, sent 3 days later, adds one new angle (e.g. a
  concrete example of a similar agent you've built), soft ask
- followup_2: <= 30 words, sent 7 days later, last touch, easy out
Plain text only. No markdown, no links unless essential.
"""
    return json_out(_SYS, prompt, _SCHEMA, max_tokens=2000)


_LI_SCHEMA = {
    "type": "object",
    "properties": {
        "note": {"type": "string"},
        "followup": {"type": "string"},
    },
    "required": ["note", "followup"],
    "additionalProperties": False,
}


def compose_linkedin_dm(lead: dict[str, Any], campaign: dict[str, Any]) -> dict[str, str]:
    """A LinkedIn connection-request note + one DM follow-up. Much shorter and
    more casual than email - LinkedIn invite notes are capped at 300 chars."""
    from_name = campaign.get("from_name") or "Saad"
    prompt = f"""\
SENDER: {from_name}
OFFER (what the sender does): {campaign['offer']}

PROSPECT
  name: {lead.get('contact_name') or 'there'} — {lead.get('contact_role') or 'Founder'}
  company: {lead['company']}
  why now: {lead.get('trigger') or 'n/a'}

Write:
- note: a LinkedIn CONNECTION REQUEST note. HARD LIMIT 300 characters. Casual,
  human, first-name only, references the why-now trigger in one short phrase,
  no pitch yet - just a reason to connect (e.g. "noticed you're scaling fast
  and doing X manually - I build custom AI agents for exactly that, would
  love to connect").
- followup: sent once they accept the connection, <= 60 words. Now make the
  actual pitch - one line on what you'd build for them, one clear ask (15-min
  call or "want a quick breakdown?"). Casual DM tone, not an email. No
  markdown, no links unless essential.
"""
    return json_out(_SYS, prompt, _LI_SCHEMA, max_tokens=800)
