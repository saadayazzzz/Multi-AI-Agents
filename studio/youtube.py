"""YouTube upload via the Data API v3.

One-time setup:
  1. Google Cloud project -> enable "YouTube Data API v3"
  2. Create an OAuth client (Desktop app) -> download the JSON as
     YOUTUBE_CLIENT_SECRETS (default: youtube_client_secret.json)
  3. Run:  python studio_cli.py auth      (opens a browser once)
     -> stores a refresh token at YOUTUBE_TOKEN (default: youtube_token.json)

Env: YOUTUBE_CLIENT_SECRETS, YOUTUBE_TOKEN, YT_PRIVACY (default 'unlisted').
"""
from __future__ import annotations

import os

SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube",
]

_CLIENT = os.getenv("YOUTUBE_CLIENT_SECRETS", "youtube_client_secret.json")
_TOKEN = os.getenv("YOUTUBE_TOKEN", "youtube_token.json")


def authorised() -> bool:
    return os.path.exists(_TOKEN)


def run_auth() -> str:
    from google_auth_oauthlib.flow import InstalledAppFlow

    if not os.path.exists(_CLIENT):
        raise SystemExit(
            f"missing {_CLIENT} — download an OAuth 'Desktop app' client JSON from "
            "Google Cloud Console and save it there (or set YOUTUBE_CLIENT_SECRETS)."
        )
    flow = InstalledAppFlow.from_client_secrets_file(_CLIENT, SCOPES)
    creds = flow.run_local_server(port=0)
    with open(_TOKEN, "w", encoding="utf-8") as f:
        f.write(creds.to_json())
    return _TOKEN


def _service():
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build

    if not authorised():
        raise RuntimeError("YouTube not authorised — run: python studio_cli.py auth")
    creds = Credentials.from_authorized_user_file(_TOKEN, SCOPES)
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        with open(_TOKEN, "w", encoding="utf-8") as f:
            f.write(creds.to_json())
    return build("youtube", "v3", credentials=creds)


def upload(
    video_path: str, title: str, description: str, tags: list[str],
    privacy: str = "unlisted", thumb_path: str | None = None,
) -> dict:
    from googleapiclient.http import MediaFileUpload

    yt = _service()
    body = {
        "snippet": {
            "title": title[:100],
            "description": description[:4900],
            "tags": tags[:30],
            "categoryId": "24",  # Entertainment
        },
        "status": {"privacyStatus": privacy, "selfDeclaredMadeForKids": False},
    }
    req = yt.videos().insert(
        part="snippet,status",
        body=body,
        media_body=MediaFileUpload(video_path, chunksize=-1, resumable=True, mimetype="video/*"),
    )
    resp = None
    while resp is None:
        _, resp = req.next_chunk()
    vid = resp["id"]

    if thumb_path and os.path.exists(thumb_path):
        try:
            yt.thumbnails().set(videoId=vid, media_body=MediaFileUpload(thumb_path)).execute()
        except Exception:  # noqa: BLE001 - thumbnail is best-effort
            pass

    return {"id": vid, "url": f"https://youtu.be/{vid}"}
