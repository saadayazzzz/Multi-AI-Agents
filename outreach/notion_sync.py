"""Mirror leads into a Notion database (official API - no ToS risk).

Setup: notion.so/my-integrations -> "New integration" -> copy the token into
NOTION_API_KEY. Then open your leads database in Notion, "..." menu -> "Add
connections" -> pick that integration, and copy the database id out of its
URL (the 32-char id right after the workspace name, before the `?v=`) into
NOTION_DATABASE_ID. Create the database with these properties first: Company
(title), Contact (text), Role (text), Domain (text), LinkedIn (url), Active
(text - when they were active on LinkedIn, e.g. "3 days ago"; blank if
unknown), Status (text), Trigger (text), Pitch (text), LinkedIn Note (text -
a short message you can copy and send yourself on LinkedIn; there's no
working automated way to find/message this person there, see
prospect.py/outreach docs for why), Date (date type - when the lead was
first prospected, from the leads table's own created_at, not when it
happened to get synced/re-synced).
"""
from __future__ import annotations

from typing import Any

from config import settings

_client = None


def _get_client():
    global _client
    if _client is None:
        if not settings.notion_api_key:
            raise RuntimeError(
                "NOTION_API_KEY is not set - add it to .env to enable Notion sync"
            )
        from notion_client import Client

        # Pin to a pre-"data sources" API version - the client's newer default
        # (2025-09-03) splits databases into a container + data-source objects,
        # which our simple single-database use case doesn't need.
        _client = Client(auth=settings.notion_api_key, notion_version="2022-06-28")
    return _client


def sync_lead(
    lead: dict[str, Any], pitch: str | None = None, linkedin_note: str | None = None,
) -> str:
    """Create or update this lead's Notion page. Returns the page id."""
    if not settings.notion_database_id:
        raise RuntimeError("NOTION_DATABASE_ID is not set - add it to .env to enable Notion sync")
    client = _get_client()

    props = {
        "Company": {"title": [{"text": {"content": lead.get("company") or "Unknown"}}]},
        "Contact": {"rich_text": [{"text": {"content": lead.get("contact_name") or ""}}]},
        "Role": {"rich_text": [{"text": {"content": lead.get("contact_role") or ""}}]},
        "Domain": {"rich_text": [{"text": {"content": lead.get("domain") or ""}}]},
        "Status": {"rich_text": [{"text": {"content": lead.get("status") or "new"}}]},
        "Trigger": {"rich_text": [{"text": {"content": (lead.get("trigger") or "")[:2000]}}]},
    }
    if lead.get("linkedin_url"):
        props["LinkedIn"] = {"url": lead["linkedin_url"]}
    if lead.get("linkedin_activity"):
        props["Active"] = {"rich_text": [{"text": {"content": lead["linkedin_activity"][:200]}}]}
    if lead.get("created_at"):
        props["Date"] = {"date": {"start": lead["created_at"].isoformat()}}
    if pitch:
        props["Pitch"] = {"rich_text": [{"text": {"content": pitch[:2000]}}]}
    if linkedin_note:
        props["LinkedIn Note"] = {"rich_text": [{"text": {"content": linkedin_note[:2000]}}]}
    
    page_id = lead.get("notion_page_id")
    if page_id:
        client.pages.update(page_id=page_id, properties=props)
        return page_id
    
    page = client.pages.create(
        parent={"database_id": settings.notion_database_id}, properties=props,
    )
    return page["id"]
