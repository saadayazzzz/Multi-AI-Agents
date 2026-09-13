"""LinkedIn posting via the Posts API.

Setup checklist (one-time, manual - cannot be automated by an agent):
  1. Create a developer app at linkedin.com/developers/apps
  2. Add the "Share on LinkedIn" product (self-serve, instant approval)
  3. Complete the OAuth consent flow once for a token with the
     `w_member_social` scope
  4. Set LINKEDIN_ACCESS_TOKEN and LINKEDIN_AUTHOR_URN ("urn:li:person:xxxx")
     in .env
"""
from __future__ import annotations

from typing import Any

import httpx

from agents.platforms import require, settings

_API = "https://api.linkedin.com/rest"
_VERSION = "202401"


def _headers(token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "LinkedIn-Version": _VERSION,
        "X-Restli-Protocol-Version": "2.0.0",
        "Content-Type": "application/json",
    }


def _upload_image(author: str, token: str, image_path: str) -> str:
    r = httpx.post(
        f"{_API}/images?action=initializeUpload",
        headers=_headers(token),
        json={"initializeUploadRequest": {"owner": author}},
        timeout=60,
    )
    r.raise_for_status()
    value = r.json()["value"]
    upload_url, image_urn = value["uploadUrl"], value["image"]

    with open(image_path, "rb") as f:
        put = httpx.put(upload_url, headers={"Authorization": f"Bearer {token}"}, content=f.read(), timeout=60)
    put.raise_for_status()
    return image_urn


def post(content: dict[str, Any], image_path: str | None) -> dict[str, str]:
    token = require("LINKEDIN_ACCESS_TOKEN", settings.linkedin_access_token, "LinkedIn")
    author = require("LINKEDIN_AUTHOR_URN", settings.linkedin_author_urn, "LinkedIn")

    body: dict[str, Any] = {
        "author": author,
        "commentary": content.get("body") or content.get("caption") or content.get("script") or "",
        "visibility": "PUBLIC",
        "distribution": {"feedDistribution": "MAIN_FEED"},
        "lifecycleState": "PUBLISHED",
    }
    if image_path:
        image_urn = _upload_image(author, token, image_path)
        body["content"] = {"media": {"id": image_urn}}

    r = httpx.post(f"{_API}/posts", headers=_headers(token), json=body, timeout=60)
    r.raise_for_status()
    post_urn = r.headers["x-restli-id"]
    return {"id": post_urn, "url": f"https://www.linkedin.com/feed/update/{post_urn}"}
