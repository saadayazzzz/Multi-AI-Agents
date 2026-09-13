"""YouTube posting.

This system never generates an actual video file, only scripts/thumbnails,
so a normal `publish` call has no video to upload. Content lands in a
distinct `ready_manual_upload` state instead of a fake success or a hard
failure - the title/description/tags/thumbnail are ready, and the user (or a
future external video-generation step) supplies the video.

If content["extra"]["video_path"] IS set (e.g. wired up later to an external
video pipeline), this uploads for real via the YouTube Data API v3.

Setup checklist for the real-upload path (manual, one-time):
  1. Create a Google Cloud project + OAuth 2.0 client for YouTube Data API v3
  2. Complete the consent flow once to obtain a refresh token
  3. Set YOUTUBE_CLIENT_SECRET_JSON and YOUTUBE_REFRESH_TOKEN in .env
"""
from __future__ import annotations

from typing import Any

from agents.platforms import require, settings


class ReadyForManualUpload(Exception):
    """Not a failure - content is ready, just needs a human to supply video."""


def post(content: dict[str, Any], image_path: str | None) -> dict[str, str]:
    extra = content.get("extra") or {}
    video_path = extra.get("video_path")
    if not video_path:
        raise ReadyForManualUpload(
            "no video file - title/description/tags/thumbnail are ready; "
            "upload the video manually or wire an external video pipeline"
        )

    require("YOUTUBE_CLIENT_SECRET_JSON", settings.youtube_client_secret_json, "YouTube")
    require("YOUTUBE_REFRESH_TOKEN", settings.youtube_refresh_token, "YouTube")

    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload
    import json as _json

    secret = _json.loads(settings.youtube_client_secret_json)["installed"]
    creds = Credentials(
        None,
        refresh_token=settings.youtube_refresh_token,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=secret["client_id"],
        client_secret=secret["client_secret"],
    )
    youtube = build("youtube", "v3", credentials=creds)

    body = {
        "snippet": {
            "title": content.get("title") or "Untitled",
            "description": extra.get("description", ""),
            "tags": extra.get("tags", []),
        },
        "status": {"privacyStatus": "public"},
    }
    resp = youtube.videos().insert(
        part="snippet,status", body=body, media_body=MediaFileUpload(video_path, resumable=True)
    ).execute()
    video_id = resp["id"]

    if image_path:
        youtube.thumbnails().set(videoId=video_id, media_body=MediaFileUpload(image_path)).execute()

    return {"id": video_id, "url": f"https://www.youtube.com/watch?v={video_id}"}
