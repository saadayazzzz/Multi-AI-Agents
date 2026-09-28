"""In-app "Connect LinkedIn" flow (official OAuth 2.0 / OpenID Connect - no
scraping, no automation of connection requests or messages, nothing that risks
the account). One person authorizes once; the resulting profile (real name,
email) becomes the default sender identity for outreach campaigns - see
run_outreach in server/brain.py.

Setup is one-time and manual (LinkedIn requires a human to register the app):
see LINKEDIN_CLIENT_ID / LINKEDIN_CLIENT_SECRET in .env.example.
"""
from __future__ import annotations

import secrets
import time
from typing import Any
from urllib.parse import urlencode

import httpx

from config import settings
from db import get_conn

_AUTHORIZE_URL = "https://www.linkedin.com/oauth/v2/authorization"
_TOKEN_URL = "https://www.linkedin.com/oauth/v2/accessToken"
_USERINFO_URL = "https://api.linkedin.com/v2/userinfo"
# sign-in only, least privilege - this build never posts on the user's behalf
_SCOPE = "openid profile email"

# CSRF state for the OAuth redirect dance. Single local server process, so an
# in-memory store (with a short expiry) is enough - no need for a DB table.
_pending_state: dict[str, float] = {}
_STATE_TTL = 600.0


def _redirect_uri() -> str:
    base = settings.public_base_url.rstrip("/") if settings.public_base_url else "http://127.0.0.1:8000"
    return f"{base}/api/linkedin/callback"


def is_configured() -> bool:
    return bool(settings.linkedin_client_id and settings.linkedin_client_secret)


def authorize_url() -> str:
    """Build the URL to send the user's browser to for LinkedIn's consent screen."""
    if not is_configured():
        raise RuntimeError(
            "LinkedIn app not configured - set LINKEDIN_CLIENT_ID and "
            "LINKEDIN_CLIENT_SECRET (see .env.example for the one-time setup steps)"
        )
    state = secrets.token_urlsafe(24)
    now = time.monotonic()
    _pending_state[state] = now
    # sweep old entries so this dict never grows unbounded
    for s, t in list(_pending_state.items()):
        if now - t > _STATE_TTL:
            _pending_state.pop(s, None)

    params = {
        "response_type": "code",
        "client_id": settings.linkedin_client_id,
        "redirect_uri": _redirect_uri(),
        "scope": _SCOPE,
        "state": state,
    }
    return f"{_AUTHORIZE_URL}?{urlencode(params)}"


def _consume_state(state: str) -> None:
    now = time.monotonic()
    ts = _pending_state.pop(state, None)
    if ts is None or now - ts > _STATE_TTL:
        raise ValueError("expired or unknown OAuth state - please try connecting again")


def complete_callback(code: str, state: str) -> dict[str, Any]:
    """Exchange the authorization code for a token, fetch the profile, persist it."""
    _consume_state(state)

    token_res = httpx.post(
        _TOKEN_URL,
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": _redirect_uri(),
            "client_id": settings.linkedin_client_id,
            "client_secret": settings.linkedin_client_secret,
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=30,
    )
    token_res.raise_for_status()
    token = token_res.json()
    access_token = token["access_token"]
    expires_in = token.get("expires_in")  # seconds, typically 60 days

    who = httpx.get(_USERINFO_URL, headers={"Authorization": f"Bearer {access_token}"}, timeout=30)
    who.raise_for_status()
    profile = who.json()  # {sub, name, email, picture, ...}
    author_urn = f"urn:li:person:{profile['sub']}"

    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO oauth_connections
                (provider, access_token, author_urn, profile_name, profile_email, scope, expires_at, connected_at)
            VALUES ('linkedin', %s, %s, %s, %s, %s,
                    CASE WHEN %s::bigint IS NULL THEN NULL ELSE now() + (%s::bigint * INTERVAL '1 second') END,
                    now())
            ON CONFLICT (provider) DO UPDATE SET
                access_token = EXCLUDED.access_token,
                author_urn = EXCLUDED.author_urn,
                profile_name = EXCLUDED.profile_name,
                profile_email = EXCLUDED.profile_email,
                scope = EXCLUDED.scope,
                expires_at = EXCLUDED.expires_at,
                connected_at = now()
            """,
            (
                access_token,
                author_urn,
                profile.get("name"),
                profile.get("email"),
                _SCOPE,
                expires_in,
                expires_in,
            ),
        )
    return {"name": profile.get("name"), "email": profile.get("email")}


def status() -> dict[str, Any]:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT profile_name, profile_email, expires_at, connected_at "
            "FROM oauth_connections WHERE provider = 'linkedin'"
        ).fetchone()
    if not row:
        return {"connected": False, "configured": is_configured()}
    return {
        "connected": True,
        "configured": True,
        "name": row["profile_name"],
        "email": row["profile_email"],
        "expires_at": row["expires_at"].isoformat() if row["expires_at"] else None,
        "connected_at": row["connected_at"].isoformat(),
    }


def disconnect() -> None:
    with get_conn() as conn:
        conn.execute("DELETE FROM oauth_connections WHERE provider = 'linkedin'")


def connected_identity() -> tuple[str | None, str | None]:
    """(name, email) of the connected profile, for personalizing outreach - or (None, None)."""
    with get_conn() as conn:
        row = conn.execute(
            "SELECT profile_name, profile_email FROM oauth_connections WHERE provider = 'linkedin'"
        ).fetchone()
    return (row["profile_name"], row["profile_email"]) if row else (None, None)
