"""Text-to-video generation. OpenAI (Sora) is the default; Replicate is a stub.

Env:
    VIDEO_PROVIDER=openai            # openai | replicate
    OPENAI_VIDEO_MODEL=sora-2
    VIDEO_SIZE=1280x720
"""
from __future__ import annotations

import os

from openai import OpenAI

from config import settings

_PROVIDER = os.getenv("VIDEO_PROVIDER", "openai").lower()
_MODEL = os.getenv("OPENAI_VIDEO_MODEL", "sora-2")
_SIZE = os.getenv("VIDEO_SIZE", "1280x720")

_oai = OpenAI(api_key=settings.openai_api_key or None)


def _read(binary) -> bytes:
    for attr in ("read", "content"):
        v = getattr(binary, attr, None)
        if callable(v):
            return v()
        if isinstance(v, (bytes, bytearray)):
            return bytes(v)
    return bytes(binary)


def generate_clip(prompt: str, seconds: int = 8) -> tuple[bytes, bytes | None]:
    """Return (mp4_bytes, thumbnail_jpg_bytes_or_None)."""
    if _PROVIDER != "openai":
        raise RuntimeError(
            f"VIDEO_PROVIDER '{_PROVIDER}' not implemented — set VIDEO_PROVIDER=openai "
            "or add a Replicate/fal adapter in studio/provider.py"
        )
    v = _oai.videos.create_and_poll(
        prompt=prompt, model=_MODEL, seconds=str(seconds), size=_SIZE,
        poll_interval_ms=5000,
    )
    status = getattr(v, "status", "")
    if status not in ("completed", "succeeded"):
        raise RuntimeError(f"video {getattr(v, 'id', '?')} status={status!r}")

    mp4 = _read(_oai.videos.download_content(v.id, variant="video"))
    thumb = None
    try:
        thumb = _read(_oai.videos.download_content(v.id, variant="thumbnail"))
    except Exception:  # noqa: BLE001
        pass
    return mp4, thumb
