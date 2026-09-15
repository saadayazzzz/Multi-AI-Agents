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
    prompt = f"""\
SENDER: {from_name}
OFFER (what the sender does): {campaign['offer']}

PROSPECT
  company: {lead['company']}  ({lead['domain']})
  contact: {lead.get('contact_name') or 'there'} — {lead.get('contact_role') or 'marketing lead'}
  why now: {lead.get('trigger') or 'n/a'}
  AI-search visibility finding: {lead.get('geo_finding') or 'not yet measured'}

Write:
- subject: <= 6 words, lowercase, specific, no clickbait
- body: <= 110 words. Open with the visibility finding (concrete). One sentence on
  what you'd do about it. Ask for a 15-min call OR "want the full breakdown?".
  Sign as {from_name}. Final line exactly: "Not relevant? Reply 'unsubscribe' and I'll stop."
- followup_1: <= 45 words, sent 3 days later, adds one new angle, soft ask
- followup_2: <= 30 words, sent 7 days later, last touch, easy out
Plain text only. No markdown, no links unless essential.
"""
    return json_out(_SYS, prompt, _SCHEMA, max_tokens=2000)
