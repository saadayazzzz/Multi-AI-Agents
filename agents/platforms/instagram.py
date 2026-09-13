"""Instagram posting via the Graph API's two-step media container flow.

Setup checklist (one-time, manual - cannot be automated by an agent):
  1. Create a Meta developer app at developers.facebook.com
  2. Add the Instagram product, link a Facebook Page to an Instagram
     Professional/Business account
  3. Add that Instagram account as an "Instagram Tester" on the app
     (Development Mode - no App Review needed for your own account)
  4. Generate a long-lived access token
  5. Set INSTAGRAM_ACCESS_TOKEN, INSTAGRAM_USER_ID, and PUBLIC_BASE_URL
     (a real public URL, e.g. via ngrok/Cloudflare Tunnel or hosting - Meta's
     servers must be able to fetch the image over the internet) in .env
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import httpx

from agents.platforms import require, settings

_API = "https://graph.facebook.com/v20.0"


def _public_url_for(image_path: str) -> str:
    base = require("PUBLIC_BASE_URL", settings.public_base_url, "Instagram")
    name = Path(image_path).name
    return f"{base.rstrip('/')}/img/content/{name}"


def _poll_container_ready(container_id: str, token: str, timeout: float = 60.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        r = httpx.get(
            f"{_API}/{container_id}",
            params={"fields": "status_code", "access_token": token},
            timeout=30,
        )
        r.raise_for_status()
        status = r.json().get("status_code")
        if status == "FINISHED":
            return
        if status == "ERROR":
            raise RuntimeError("Instagram media container failed to process")
        time.sleep(2)
    raise RuntimeError("Instagram media container timed out")


def post(content: dict[str, Any], image_path: str | None) -> dict[str, str]:
    token = require("INSTAGRAM_ACCESS_TOKEN", settings.instagram_access_token, "Instagram")
    ig_user_id = require("INSTAGRAM_USER_ID", settings.instagram_user_id, "Instagram")
    if not image_path:
        raise RuntimeError(
            "Instagram requires an image - Visual Studio has not produced one for this content yet"
        )

    image_url = _public_url_for(image_path)
    r1 = httpx.post(
        f"{_API}/{ig_user_id}/media",
        params={
            "image_url": image_url,
            "caption": content.get("caption") or "",
            "access_token": token,
        },
        timeout=60,
    )
    r1.raise_for_status()
    container_id = r1.json()["id"]

    _poll_container_ready(container_id, token)

    r2 = httpx.post(
        f"{_API}/{ig_user_id}/media_publish",
        params={"creation_id": container_id, "access_token": token},
        timeout=60,
    )
    r2.raise_for_status()
    media_id = r2.json()["id"]
    return {"id": media_id, "url": f"https://www.instagram.com/p/{media_id}/"}
