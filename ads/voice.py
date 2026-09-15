"""Free AI voiceover via edge-tts (Microsoft Edge's read-aloud voices, no key).

Also returns word-level timestamps so captions.py can burn captions that are
tightly synced to the spoken audio, not just evenly split by duration.
"""
from __future__ import annotations

import asyncio
import os
from typing import Any

import edge_tts

_VOICE = os.getenv("ADS_VOICE", "en-US-AndrewMultilingualNeural")


async def _synthesize(text: str, voice: str) -> tuple[bytes, list[dict[str, Any]]]:
    communicate = edge_tts.Communicate(text, voice, boundary="WordBoundary")
    audio = bytearray()
    words: list[dict[str, Any]] = []
    async for chunk in communicate.stream():
        if chunk["type"] == "audio":
            audio.extend(chunk["data"])
        elif chunk["type"] == "WordBoundary":
            words.append({
                "word": chunk["text"],
                "start": chunk["offset"] / 1e7,  # 100ns ticks -> seconds
                "end": (chunk["offset"] + chunk["duration"]) / 1e7,
            })
    return bytes(audio), words


def synthesize(text: str, voice: str | None = None) -> tuple[bytes, list[dict[str, Any]]]:
    """Return (mp3_bytes, word_timings) for the given script text."""
    return asyncio.run(_synthesize(text, voice or _VOICE))
