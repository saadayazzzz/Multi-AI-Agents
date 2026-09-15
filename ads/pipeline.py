"""niche/product -> ad script -> AI voiceover + B-roll -> assemble -> (upload)."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from agents.llm import generate_image
from agents.reporter import report
from config import settings
from db.database import get_conn
from studio import thumbnail, youtube

from ads import assemble as assemble_mod
from ads import captions, voice
from ads.script import script

_AI_DISCLOSURE = "\n\nThis ad was created with AI - script, voiceover, and visuals."


def make_ugc_ad(
    niche: str,
    product: str | None = None,
    seconds: int = 30,
    upload: bool = False,
) -> dict[str, Any]:
    privacy = os.getenv("YT_PRIVACY", "unlisted")
    report(f"ads: '{niche}'" + (f" / {product}" if product else "") + f" — target {seconds}s (privacy: {privacy})")

    sc = script(niche, product=product, seconds=seconds)
    with get_conn() as conn:
        ad_id = conn.execute(
            """
            INSERT INTO ads (niche, product, hook, script, seconds, privacy)
            VALUES (%s, %s, %s, %s, %s, %s) RETURNING id
            """,
            (niche, product, sc["hook"], sc["script"], seconds, privacy),
        ).fetchone()["id"]

    work = Path(settings.output_dir) / "ads" / str(ad_id)
    work.mkdir(parents=True, exist_ok=True)

    try:
        report("  writing voiceover")
        audio, words = voice.synthesize(sc["script"])

        report(f"  generating {len(sc['visual_prompts'])} B-roll shots")
        images: list[bytes] = []
        for i, prompt in enumerate(sc["visual_prompts"], 1):
            report(f"    shot {i}/{len(sc['visual_prompts'])}: {prompt[:70]}")
            images.append(generate_image(prompt, size=settings.image_size))

        srt_path = None
        if words:
            srt_path = str(work / "captions.srt")
            captions.write_srt(words, srt_path)

        final = str(work / "final.mp4")
        assemble_mod.assemble(images, audio, srt_path, final)

        thumb = str(work / "thumb.jpg")
        thumbnail.frame_thumb(final, thumb)

        with get_conn() as conn:
            conn.execute(
                "UPDATE ads SET path = %s, thumb_path = %s, status = 'rendered' WHERE id = %s",
                (final, thumb, ad_id),
            )
        report(f"  rendered -> {final}")
        out: dict[str, Any] = {"id": ad_id, "title": sc["title"], "path": final, "thumb": thumb}

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
                        "UPDATE ads SET youtube_id = %s, youtube_url = %s, status = 'uploaded' "
                        "WHERE id = %s",
                        (r["id"], r["url"], ad_id),
                    )
                out.update(r)
                report(f"  uploaded ({privacy}) -> {r['url']}")
        return out

    except Exception as e:  # noqa: BLE001
        with get_conn() as conn:
            conn.execute("UPDATE ads SET status = 'failed', error = %s WHERE id = %s", (str(e), ad_id))
        raise
