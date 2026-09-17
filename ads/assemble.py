"""ffmpeg assembly for faceless UGC ads: B-roll images -> slow zoom/pan ->
concat -> mux voiceover -> burn captions. Vertical 9:16, matches TikTok/
Reels/Shorts framing.
"""
from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

_W, _H = 1080, 1920
_FPS = 30


def _run(args: list[str]) -> None:
    p = subprocess.run(args, capture_output=True, text=True)
    if p.returncode != 0:
        raise RuntimeError(f"ffmpeg failed: {' '.join(args[:6])} …\n{p.stderr[-800:]}")


def _probe_duration(path: str) -> float:
    p = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", path],
        capture_output=True, text=True,
    )
    return float(p.stdout.strip() or 0.0)


def _zoom_segment(image_path: Path, seconds: float, out_path: Path) -> None:
    frames = max(1, round(seconds * _FPS))
    zoompan = (
        f"zoompan=z='min(1+0.0006*on,1.15)':d=1:s={_W}x{_H}:fps={_FPS}"
    )
    vf = (
        f"scale={_W}:{_H}:force_original_aspect_ratio=increase,"
        f"crop={_W}:{_H},{zoompan},format=yuv420p"
    )
    _run([
        "ffmpeg", "-y", "-loop", "1", "-framerate", str(_FPS), "-i", str(image_path),
        "-frames:v", str(frames), "-vf", vf,
        "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-an", str(out_path),
    ])


def assemble(
    images: list[bytes],
    audio_mp3: bytes,
    srt_path: str | None,
    out_path: str,
) -> str:
    """Build the vertical ad video and write it to out_path."""
    tmp = Path(tempfile.mkdtemp(prefix="ads_"))

    audio_path = tmp / "voice.mp3"
    audio_path.write_bytes(audio_mp3)
    duration = _probe_duration(str(audio_path)) or 30.0
    each = duration / max(1, len(images))

    segs: list[Path] = []
    for i, img in enumerate(images):
        src = tmp / f"src{i}.jpg"
        src.write_bytes(img)
        seg = tmp / f"seg{i}.mp4"
        _zoom_segment(src, each, seg)
        segs.append(seg)

    listf = tmp / "list.txt"
    listf.write_text("".join(f"file '{p.as_posix()}'\n" for p in segs), encoding="utf-8")
    video = tmp / "video.mp4"
    _run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(listf), "-c", "copy", str(video)])

    muxed = tmp / "muxed.mp4"
    _run([
        "ffmpeg", "-y", "-i", str(video), "-i", str(audio_path),
        "-map", "0:v:0", "-map", "1:a:0", "-c:v", "copy",
        "-filter:a", "loudnorm=I=-16:TP=-1.5:LRA=11", "-c:a", "aac", "-b:a", "192k",
        "-shortest", str(muxed),
    ])

    _burn_captions(str(muxed), srt_path, out_path, copy_video_if_no_captions=True)
    return out_path


def _burn_captions(
    in_path: str, srt_path: str | None, out_path: str, *, copy_video_if_no_captions: bool
) -> None:
    args = ["ffmpeg", "-y", "-i", in_path]
    if srt_path and Path(srt_path).exists():
        # ffmpeg's filter-graph parser treats ':' and '\' specially, so the
        # subtitles filter needs the path escaped even on Windows drive paths.
        escaped = Path(srt_path).as_posix().replace(":", "\\:")
        if Path(srt_path).suffix.lower() == ".ass":
            # .ass carries its own [V4+ Styles] + per-line pop animation
            # (ads/captions.py) - force_style would stomp on both, so leave
            # it out and let the file's own styling render as authored.
            vf = f"subtitles='{escaped}'"
        else:
            vf = (
                f"subtitles='{escaped}':force_style="
                "'FontName=Arial Black,FontSize=17,PrimaryColour=&H00FFFFFF,"
                "OutlineColour=&H00000000,BorderStyle=1,Outline=3,Shadow=0,"
                "Alignment=2,MarginV=140'"
            )
        args += ["-vf", vf, "-c:v", "libx264", "-preset", "medium", "-crf", "20"]
    elif copy_video_if_no_captions:
        args += ["-c:v", "copy"]
    else:
        args += ["-c:v", "libx264", "-preset", "medium", "-crf", "20"]
    args += ["-c:a", "copy", "-movflags", "+faststart", out_path]
    _run(args)


def assemble_avatar(talking_head_mp4: bytes, srt_path: str | None, out_path: str) -> str:
    """Fit a square/near-square talking-head clip (audio already baked in by
    the animator) into the 9:16 frame - a blurred, scaled copy of itself
    fills the background, the sharp original sits centered on top - then
    burn captions. Matches the visual language of assemble()'s B-roll ads.
    """
    tmp = Path(tempfile.mkdtemp(prefix="ads_avatar_"))
    src = tmp / "head.mp4"
    src.write_bytes(talking_head_mp4)

    fitted = tmp / "fitted.mp4"
    filter_complex = (
        f"[0:v]scale={_W}:{_H}:force_original_aspect_ratio=increase,"
        f"crop={_W}:{_H},gblur=sigma=25[bg];"
        f"[0:v]scale={_W}:-2[fg];"
        f"[bg][fg]overlay=(W-w)/2:(H-h)/2:format=auto,format=yuv420p[v]"
    )
    _run([
        "ffmpeg", "-y", "-i", str(src),
        "-filter_complex", filter_complex, "-map", "[v]", "-map", "0:a",
        "-c:v", "libx264", "-preset", "medium", "-crf", "20",
        "-filter:a", "loudnorm=I=-16:TP=-1.5:LRA=11", "-c:a", "aac", "-b:a", "192k",
        str(fitted),
    ])

    _burn_captions(str(fitted), srt_path, out_path, copy_video_if_no_captions=False)
    return out_path
