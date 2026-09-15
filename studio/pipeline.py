"""theme -> clip prompts -> AI video clips -> assemble -> thumbnail -> (upload)."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from agents.reporter import report
from config import settings
from db.database import get_conn
from studio import assemble, provider, thumbnail, youtube
from studio.script import script

_AI_DISCLOSURE = "\n\nSome shots in this video were created with AI video generation."


def make_video(
    theme: str,
    clips: int = 3,
    seconds_each: int = 8,
    target_seconds: int | None = None,
    upload: bool = False,
    audio: str | None = None,
) -> dict[str, Any]:
    clips = max(1, min(clips, 8))
    privacy = os.getenv("YT_PRIVACY", "unlisted")
    report(f"studio: '{theme}' — {clips} clips x {seconds_each}s (privacy: {privacy})")

    sc = script(theme, clips)
    with get_conn() as conn:
        vid = conn.execute(
            """
            INSERT INTO videos (theme, title, description, tags, clip_count, seconds, privacy)
            VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id
            """,
            (theme, sc["title"], sc["description"], sc["tags"], clips,
             target_seconds or clips * seconds_each, privacy),
        ).fetchone()["id"]

    work = Path(settings.output_dir) / "videos" / str(vid)
    work.mkdir(parents=True, exist_ok=True)

    try:
        clip_paths: list[str] = []
        thumb_bytes: bytes | None = None
        for i, cl in enumerate(sc["clips"][:clips], 1):
            report(f"  clip {i}/{clips}: {cl['object']}")
            mp4, tb = provider.generate_clip(cl["prompt"], seconds=seconds_each)
            p = work / f"clip{i}.mp4"
            p.write_bytes(mp4)
            clip_paths.append(str(p))
            if tb and not thumb_bytes:
                thumb_bytes = tb

        final = str(work / "final.mp4")
        assemble.assemble(
            clip_paths, final,
            target_seconds=target_seconds,
            audio=audio or os.getenv("STUDIO_AUDIO"),
        )
        thumb = str(work / "thumb.jpg")
        if thumb_bytes:
            thumbnail.write_thumb(thumb_bytes, thumb)
        else:
            thumbnail.frame_thumb(final, thumb)

        with get_conn() as conn:
            conn.execute(
                "UPDATE videos SET path = %s, thumb_path = %s, status = 'rendered' WHERE id = %s",
                (final, thumb, vid),
            )
        report(f"  rendered -> {final}")
        out: dict[str, Any] = {"id": vid, "title": sc["title"], "path": final, "thumb": thumb}

        if upload:
            if not youtube.authorised():
                report("  upload skipped — run `python studio_cli.py auth` first")
                out["upload"] = "not authorised"
            else:
                r = youtube.upload(
                    final, sc["title"], sc["description"] + _AI_DISCLOSURE,
                    sc["tags"], privacy, thumb,
                )
                with get_conn() as conn:
                    conn.execute(
                        "UPDATE videos SET youtube_id = %s, youtube_url = %s, status = 'uploaded' "
                        "WHERE id = %s",
                        (r["id"], r["url"], vid),
                    )
                out.update(r)
                report(f"  uploaded ({privacy}) -> {r['url']}")
        return out

    except Exception:
        with get_conn() as conn:
            conn.execute("UPDATE videos SET status = 'failed' WHERE id = %s", (vid,))
        raise
