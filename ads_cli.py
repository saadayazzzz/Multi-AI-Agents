"""Ad Studio — faceless AI UGC ad creatives for YouTube Shorts.

    python ads_cli.py initdb
    python ads_cli.py make "skincare" --product "vitamin C serum" --seconds 30
    python ads_cli.py make "healthcare scheduling software" --upload
    python ads_cli.py make "fitness coaching" --avatar   # talking AI presenter (needs ComfyUI SadTalker)
    python ads_cli.py list

Needs ffmpeg on PATH. Voiceover is free (edge-tts, no key). B-roll images use
the same free image path as the content pipeline (Gemini, falling back to
Pollinations.ai). --upload reuses the Video Studio's YouTube OAuth token —
run `python studio_cli.py auth` once first. Uploads default to UNLISTED and
carry an AI-generated-content disclosure; make them public yourself after
review.
"""
from __future__ import annotations

import argparse
import sys

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from ads.db import init_ads_db
from ads.pipeline import make_ugc_ad
from db.database import wait_for_db


def main() -> None:
    ap = argparse.ArgumentParser(prog="ads")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("initdb")

    m = sub.add_parser("make")
    m.add_argument("niche")
    m.add_argument("--product", help="specific product/offer, if any")
    m.add_argument("--seconds", type=int, default=30, help="target length in seconds")
    m.add_argument("--avatar", action="store_true", help="talking AI presenter instead of faceless B-roll")
    m.add_argument("--upload", action="store_true")

    sub.add_parser("list")

    args = ap.parse_args()

    wait_for_db()
    init_ads_db()

    if args.cmd == "initdb":
        return
    if args.cmd == "make":
        r = make_ugc_ad(
            args.niche, product=args.product, seconds=args.seconds,
            avatar=args.avatar, upload=args.upload,
        )
        print("\n" + "\n".join(f"  {k}: {v}" for k, v in r.items()))
    elif args.cmd == "list":
        from db.database import get_conn

        with get_conn() as conn:
            rows = conn.execute(
                "SELECT id, status, privacy, niche, product, youtube_url FROM ads ORDER BY id DESC"
            ).fetchall()
        for r in rows:
            print(f"  [{r['status']:<9}] {r['privacy']:<8} #{r['id']} {r['niche']}"
                  + (f" / {r['product']}" if r['product'] else "")
                  + f"  {r['youtube_url'] or ''}")


if __name__ == "__main__":
    main()
