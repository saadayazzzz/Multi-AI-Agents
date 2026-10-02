"""Message content for campaign steps: 'same' templates and 'ai' writing."""
from __future__ import annotations

import os
import re
from typing import Any

_VARS = {
    "firstname": lambda c: c.get("first_name") or "there",
    "lastname": lambda c: c.get("last_name") or "",
    "company": lambda c: c.get("company") or "your company",
}
_VAR_RE = re.compile(r"\[(FirstName|LastName|Company)\]", re.I)


def render(text: str, contact: dict[str, Any]) -> str:
    out = _VAR_RE.sub(lambda m: _VARS[m.group(1).lower()](contact), text or "")
    return re.sub(r"[ \t]{2,}", " ", out).strip()


_GOALS = {
    "demos": "book a short call / demo - one clear, low-friction ask",
    "warm": "start a genuine conversation - no hard ask, a question they'd want to answer",
}

_SYS = (
    "You write outbound messages a busy decision-maker actually answers: short, specific "
    "to them, plain language, no hype, no flattery, no buzzwords, never pretending to know "
    "them. Lead with why you're reaching out NOW (their signal), then one line of value, "
    "then the ask. Never invent facts about them beyond what you're given."
)

_SCHEMA = {
    "type": "object",
    "properties": {"subject": {"type": "string"}, "body": {"type": "string"}},
    "required": ["subject", "body"],
    "additionalProperties": False,
}

_SHAPE = {
    "invitationNote": "a LinkedIn connection note, HARD LIMIT {cap} characters, no pitch, just a reason to connect",
    "message": "a LinkedIn DM, <= 450 characters, casual, first name only, no links unless essential",
    "voiceMessage": "a 20-second voice note script, spoken style, <= 60 words",
    "email": "a cold email: subject <= 6 words lowercase; body <= 110 words, plain text, sign with the sender name",
}


def ai_write(step: dict, contact: dict, campaign: dict, prior: list[dict], note_cap: int = 180) -> dict[str, str]:
    from agents.llm import json_out

    offer = campaign.get("offer") or os.getenv("SALES_OFFER") or "custom AI agents and automation"
    sender = campaign.get("sender_name") or os.getenv("SALES_SENDER_NAME") or "me"
    history = "\n".join(
        f"- step {p['step_number']} ({p['type']}): {(p.get('body') or '')[:300]}" for p in prior if p.get("body")
    ) or "- none yet (this is the first touch)"
    prompt = f"""\
SENDER: {sender}
WHAT THE SENDER OFFERS: {offer}
GOAL: {_GOALS.get(campaign.get('goal') or 'demos', campaign.get('goal'))}
TONE: {campaign.get('tone') or 'conversational'}
LANGUAGE: {campaign.get('language') or 'en-US'}

PROSPECT
  name: {contact.get('full_name')}
  role: {contact.get('job_title') or contact.get('headline') or '?'}
  company: {contact.get('company') or '?'}
  location: {contact.get('location') or '?'}
  why now (their signal): {(contact.get('intent') or 'n/a')[:600]}

ALREADY SENT IN THIS SEQUENCE
{history}

Write step {step['step_number']}: {_SHAPE[step['type']].format(cap=note_cap)}.
Follow-ups must add something new, not repeat earlier steps. For non-email steps
set subject to "".
"""
    out = json_out(_SYS, prompt, _SCHEMA, max_tokens=900)
    body = out["body"].strip()
    if step["type"] == "invitationNote":
        body = body[:note_cap]
    if step["type"] == "message":
        body = body[:1900]
    return {"subject": out.get("subject", "").strip(), "body": body}


def content_for(step: dict, contact: dict, campaign: dict, prior: list[dict], note_cap: int = 180) -> dict[str, str]:
    t = step["type"]
    if t in ("invitation", "visitProfile", "likePosts"):
        return {"subject": "", "body": ""}
    if t == "invitationNote":
        return {"subject": "", "body": render(step["note"], contact)[:note_cap]}
    if t == "voiceMessage":
        return {"subject": "", "body": step.get("url", "")}
    if step.get("message_mode") == "same":
        return {"subject": render(step.get("subject") or "", contact), "body": render(step["message"], contact)}
    return ai_write(step, contact, campaign, prior, note_cap)


def split_paragraphs(body: str) -> list[str]:
    """splitLinkedinMessagesIntoConversation: one DM per paragraph."""
    parts = [p.strip() for p in re.split(r"\n\s*\n", body or "") if p.strip()]
    return parts or [body]
