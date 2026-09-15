"""Word timings -> burned-in captions (TikTok-style short phrase chunks)."""
from __future__ import annotations

from pathlib import Path
from typing import Any

_WORDS_PER_CHUNK = 4


def _srt_ts(seconds: float) -> str:
    ms = round(seconds * 1000)
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def write_srt(words: list[dict[str, Any]], out_path: str, words_per_chunk: int = _WORDS_PER_CHUNK) -> str:
    """Group words into short on-screen chunks and write an .srt file."""
    lines = []
    idx = 1
    for i in range(0, len(words), words_per_chunk):
        chunk = words[i : i + words_per_chunk]
        if not chunk:
            continue
        start, end = chunk[0]["start"], chunk[-1]["end"]
        text = " ".join(w["word"] for w in chunk)
        lines.append(f"{idx}\n{_srt_ts(start)} --> {_srt_ts(end)}\n{text}\n")
        idx += 1
    Path(out_path).write_text("\n".join(lines), encoding="utf-8")
    return out_path
