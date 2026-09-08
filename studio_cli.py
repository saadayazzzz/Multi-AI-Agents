"""Studio — AI 'objects cutting' ASMR videos for YouTube.

    python studio_cli.py initdb
    python studio_cli.py auth                          # one-time YouTube OAuth
    python studio_cli.py make "soap cutting" --clips 3 --seconds 8
    python studio_cli.py make "glass fruit slicing" --clips 4 --target 40 --upload
    python studio_cli.py list

Needs ffmpeg on PATH, an OpenAI key with video (Sora) access, and — for
--upload — the YouTube OAuth token from `auth`. Uploads default to UNLISTED and
carry an AI-generated-content disclosure; make them public yourself after review.
"""
from __future__ import annotations

import argparse
import sys

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from db.database import wait_for_db
from studio.db import init_studio_db
from studio.pipeline import make_video
from studio.youtube import run_auth


def main() -> None:
    ap = argparse.ArgumentParser(prog="studio")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("initdb")
    sub.add_parser("auth")

    m = sub.add_parser("make")
    m.add_argument("theme")
    m.add_argument("--clips", type=int, default=3)
    m.add_argument("--seconds", type=int, default=8, help="length of each AI clip")
    m.add_argument("--target", type=int, help="final video length (loops clips to fill)")
    m.add_argument("--audio", help="path to a background ASMR/music track")
    m.add_argument("--upload", action="store_true")

    sub.add_parser("list")

    args = ap.parse_args()

    if args.cmd == "auth":
        print("saved", run_auth())
        return

    wait_for_db()
    init_studio_db()

    if args.cmd == "initdb":
        return
    if args.cmd == "make":
        r = make_video(args.theme, args.clips, args.seconds, args.target, args.upload, args.audio)
        print("\n" + "\n".join(f"  {k}: {v}" for k, v in r.items()))
    elif args.cmd == "list":
        from db.database import get_conn

        with get_conn() as conn:
            rows = conn.execute(
                "SELECT id, status, privacy, theme, title, youtube_url FROM videos ORDER BY id DESC"
            ).fetchall()
        for r in rows:
            print(f"  [{r['status']:<8}] {r['privacy']:<8} #{r['id']} {r['theme']}  "
                  f"{r['youtube_url'] or r['title'] or ''}")


if __name__ == "__main__":
    main()
