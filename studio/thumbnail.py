"""Thumbnail: prefer the provider's still; else grab a frame from the final video."""
from __future__ import annotations

import subprocess
from pathlib import Path


def frame_thumb(video_path: str, out_jpg: str, at: str = "00:00:01") -> str:
    p = subprocess.run(
        ["ffmpeg", "-y", "-ss", at, "-i", video_path, "-frames:v", "1", "-q:v", "2", out_jpg],
        capture_output=True, text=True,
    )
    if p.returncode != 0:
        raise RuntimeError(f"thumbnail grab failed:\n{p.stderr[-400:]}")
    return out_jpg


def write_thumb(data: bytes, out_jpg: str) -> str:
    Path(out_jpg).write_bytes(data)
    return out_jpg
