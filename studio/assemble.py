"""ffmpeg assembly: normalise clips -> concat -> loop to length -> mux audio."""
from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

_VF = (
    "scale=1920:1080:force_original_aspect_ratio=increase,"
    "crop=1920:1080,fps=30,format=yuv420p"
)


def _run(args: list[str]) -> None:
    p = subprocess.run(args, capture_output=True, text=True)
    if p.returncode != 0:
        raise RuntimeError(f"ffmpeg failed: {' '.join(args[:4])} …\n{p.stderr[-800:]}")


def assemble(
    clips: list[str],
    out_path: str,
    target_seconds: int | None = None,
    audio: str | None = None,
) -> str:
    tmp = Path(tempfile.mkdtemp(prefix="studio_"))

    norm: list[Path] = []
    for i, c in enumerate(clips):
        n = tmp / f"n{i}.mp4"
        _run([
            "ffmpeg", "-y", "-i", c, "-vf", _VF,
            "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-an", str(n),
        ])
        norm.append(n)

    listf = tmp / "list.txt"
    listf.write_text("".join(f"file '{p.as_posix()}'\n" for p in norm), encoding="utf-8")
    cur = tmp / "concat.mp4"
    _run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(listf), "-c", "copy", str(cur)])

    if target_seconds:
        looped = tmp / "looped.mp4"
        _run([
            "ffmpeg", "-y", "-stream_loop", "-1", "-i", str(cur),
            "-t", str(target_seconds), "-c", "copy", str(looped),
        ])
        cur = looped

    args = ["ffmpeg", "-y", "-i", str(cur)]
    if audio and Path(audio).exists():
        args += [
            "-stream_loop", "-1", "-i", audio, "-shortest",
            "-map", "0:v:0", "-map", "1:a:0",
            "-c:v", "copy",
            "-filter:a", "loudnorm=I=-16:TP=-1.5:LRA=11", "-c:a", "aac", "-b:a", "192k",
        ]
    else:
        args += ["-c:v", "copy", "-an"]
    args += ["-movflags", "+faststart", out_path]
    _run(args)
    return out_path
