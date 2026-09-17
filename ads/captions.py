"""Word timings -> burned-in captions (TikTok-style short phrase chunks).

Writes .ass (not plain .srt) so each caption gets a quick "pop" entrance
animation (via libass override tags) timed to that exact chunk's real
start/end from the voiceover - the animation is driven by the actual word
timestamps, so its timing naturally follows whatever pace each script reads
at rather than a fixed, one-size-fits-all rhythm.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

_WORDS_PER_CHUNK = 3
# Matches the ads output frame (ads/assemble.py _W, _H) - PlayRes must match
# so the font size below renders at a consistent, predictable on-screen size.
_RES_X, _RES_Y = 1080, 1920


def _ass_ts(seconds: float) -> str:
    cs = round(seconds * 100)  # centiseconds - ASS's native time unit
    h, cs = divmod(cs, 360_000)
    m, cs = divmod(cs, 6_000)
    s, cs = divmod(cs, 100)
    return f"{h:d}:{m:02d}:{s:02d}.{cs:02d}"


_HEADER = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {_RES_X}
PlayResY: {_RES_Y}
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Arial Black,74,&H00FFFFFF,&H000000FF,&H00000000,&H00000000,-1,0,0,0,100,100,0,0,1,4,0,2,60,60,150,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

# Pop-in: starts small + transparent, overshoots past full size, settles back
# - the classic caption "bounce" - each chunk plays this fresh on its own cue,
# so pacing follows the words themselves rather than a canned animation loop.
_POP = r"{\fscx55\fscy55\alpha&HFF&\t(0,90,\fscx118\fscy118\alpha&H00&)\t(90,170,\fscx100\fscy100)}"


def write_ass(words: list[dict[str, Any]], out_path: str, words_per_chunk: int = _WORDS_PER_CHUNK) -> str:
    """Group words into short on-screen chunks and write an animated .ass file."""
    lines = [_HEADER]
    for i in range(0, len(words), words_per_chunk):
        chunk = words[i : i + words_per_chunk]
        if not chunk:
            continue
        start, end = chunk[0]["start"], chunk[-1]["end"]
        text = " ".join(w["word"] for w in chunk).replace("\n", " ")
        lines.append(
            f"Dialogue: 0,{_ass_ts(start)},{_ass_ts(end)},Default,,0,0,0,,{_POP}{text}\n"
        )
    Path(out_path).write_text("".join(lines), encoding="utf-8")
    return out_path


# Kept for anything still generating plain SRT (e.g. external tooling); the
# ads pipeline itself now uses write_ass() for animated captions.
def _srt_ts(seconds: float) -> str:
    ms = round(seconds * 1000)
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def write_srt(words: list[dict[str, Any]], out_path: str, words_per_chunk: int = _WORDS_PER_CHUNK) -> str:
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
