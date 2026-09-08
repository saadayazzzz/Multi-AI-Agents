"""Text-to-video generation.

    VIDEO_PROVIDER=openai   -> OpenAI Sora (paid; needs Sora API access)
    VIDEO_PROVIDER=hf       -> Hugging Face Inference (free tier; open models)

Env:
    OPENAI_VIDEO_MODEL=sora-2
    VIDEO_SIZE=1280x720
    HF_TOKEN=hf_xxx                       # free from huggingface.co/settings/tokens
    HF_VIDEO_MODEL=Lightricks/LTX-Video
"""
from __future__ import annotations

import os

from config import settings

_PROVIDER = os.getenv("VIDEO_PROVIDER", "openai").lower()


def _read(binary) -> bytes:
    for attr in ("read", "content"):
        v = getattr(binary, attr, None)
        if callable(v):
            return v()
        if isinstance(v, (bytes, bytearray)):
            return bytes(v)
    return bytes(binary)


# --------------------------------------------------------------------------- #
def _openai_clip(prompt: str, seconds: int) -> tuple[bytes, bytes | None]:
    from openai import OpenAI

    oai = OpenAI(api_key=settings.openai_api_key or None)
    model = os.getenv("OPENAI_VIDEO_MODEL", "sora-2")
    size = os.getenv("VIDEO_SIZE", "1280x720")

    v = oai.videos.create_and_poll(
        prompt=prompt, model=model, seconds=str(seconds), size=size,
        poll_interval_ms=5000,
    )
    status = getattr(v, "status", "")
    if status not in ("completed", "succeeded"):
        raise RuntimeError(f"video {getattr(v, 'id', '?')} status={status!r}")

    mp4 = _read(oai.videos.download_content(v.id, variant="video"))
    thumb = None
    try:
        thumb = _read(oai.videos.download_content(v.id, variant="thumbnail"))
    except Exception:  # noqa: BLE001
        pass
    return mp4, thumb


# --------------------------------------------------------------------------- #
def _hf_clip(prompt: str, seconds: int) -> tuple[bytes, bytes | None]:
    from huggingface_hub import InferenceClient

    token = os.getenv("HF_TOKEN") or os.getenv("HUGGINGFACE_API_KEY")
    if not token:
        raise RuntimeError(
            "VIDEO_PROVIDER=hf needs HF_TOKEN in .env "
            "(free from https://huggingface.co/settings/tokens)"
        )
    model = os.getenv("HF_VIDEO_MODEL", "Lightricks/LTX-Video")
    client = InferenceClient(token=token, provider="auto")

    mp4 = client.text_to_video(
        prompt,
        model=model,
        num_frames=min(int(seconds) * 24, 161),
    )
    return bytes(mp4), None  # no thumbnail from HF -> pipeline grabs a frame


# --------------------------------------------------------------------------- #
_ADAPTERS = {"openai": _openai_clip, "hf": _hf_clip}


def generate_clip(prompt: str, seconds: int = 8) -> tuple[bytes, bytes | None]:
    """Return (mp4_bytes, thumbnail_jpg_bytes_or_None)."""
    fn = _ADAPTERS.get(_PROVIDER)
    if not fn:
        raise RuntimeError(
            f"VIDEO_PROVIDER '{_PROVIDER}' unknown — use 'openai' or 'hf'"
        )
    return fn(prompt, seconds)
