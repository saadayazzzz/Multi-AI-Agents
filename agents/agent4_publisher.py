"""Agent 4 - Publisher.

Posts a finished content piece live to its platform - only ever when
explicitly approved (by content_id via chat/dashboard, or "post it" which
resolves to the most recently prepared 'ready' piece). Dispatches to
agents/platforms/{linkedin,instagram,youtube}.py. A missing-credential or
platform-API error never crashes the caller - the content piece is marked
failed/ready_manual_upload with a clear reason and work continues.

Also exposes run_full_cycle(), which chains Trend Scout -> Content Studio ->
Visual Studio -> Publisher for one platform in a single call - used both by
the orchestrator's convenience tool and the worker's autonomous idle hook.
"""
from __future__ import annotations

from typing import Any

from agents.platforms import instagram, linkedin, youtube
from agents.platforms.youtube import ReadyForManualUpload
from agents.reporter import report
from db import get_conn

_POSTERS = {"linkedin": linkedin.post, "instagram": instagram.post, "youtube": youtube.post}


def _load(conn, content_id: int | None) -> dict[str, Any]:
    if content_id:
        row = conn.execute(
            """
            SELECT c.*, i.rel_path AS image_rel_path
            FROM content_pieces c
            LEFT JOIN content_images i ON i.content_id = c.id
            WHERE c.id = %s
            """,
            (content_id,),
        ).fetchone()
    else:
        # "post it" with no id given - approve the most recently prepared piece.
        row = conn.execute(
            """
            SELECT c.*, i.rel_path AS image_rel_path
            FROM content_pieces c
            LEFT JOIN content_images i ON i.content_id = c.id
            WHERE c.status = 'ready'
            ORDER BY c.created_at DESC LIMIT 1
            """
        ).fetchone()
    if not row:
        raise SystemExit(f"agent4: no ready content found" if not content_id else f"agent4: no content #{content_id}")
    return row


def publish(content_id: int | None = None) -> dict[str, Any]:
    with get_conn() as conn:
        content = _load(conn, content_id)
        content_id = content["id"]
        platform = content["platform"]
        poster = _POSTERS.get(platform)
        if poster is None:
            raise ValueError(f"unknown platform: {platform}")

        import os

        image_path = None
        if content.get("image_rel_path"):
            image_path = os.path.join("output", "content", os.path.basename(content["image_rel_path"]))

        try:
            result = poster(content, image_path)
            conn.execute(
                "UPDATE content_pieces SET status='posted', external_post_id=%s, "
                "external_url=%s, posted_at=now(), error=NULL WHERE id=%s",
                (result["id"], result["url"], content_id),
            )
            report(f"agent4: posted {platform} content #{content_id} -> {result['url']}",
                   kind="status", content_id=content_id, platform=platform)
            return {"content_id": content_id, "status": "posted", **result}
        except ReadyForManualUpload as e:
            conn.execute(
                "UPDATE content_pieces SET status='ready_manual_upload', error=%s WHERE id=%s",
                (str(e), content_id),
            )
            report(f"agent4: {platform} content #{content_id} ready for manual upload ({e})",
                   kind="status", content_id=content_id, platform=platform)
            return {"content_id": content_id, "status": "ready_manual_upload", "error": str(e)}
        except Exception as e:  # noqa: BLE001 - never let one bad post break the run
            conn.execute(
                "UPDATE content_pieces SET status='failed', error=%s WHERE id=%s",
                (str(e), content_id),
            )
            report(f"agent4: failed to post {platform} content #{content_id} ({e})", kind="error",
                   content_id=content_id, platform=platform)
            return {"content_id": content_id, "status": "failed", "error": str(e)}


def run_full_cycle(platform: str, topic: str | None = None) -> dict[str, Any]:
    """Research -> write -> visualize. Stops at 'ready' - does NOT publish.

    Posting requires explicit human approval (publish() / the dashboard's
    Approve & Post button / a chat command like "post content #5"), never
    happens automatically, whether this is called from a user request or the
    worker's autonomous idle cycle.
    """
    from agents.agent1_trends import scout
    from agents.agent2_content import write
    from agents.agent3_visuals import visualize

    scout(platform)
    piece = write(platform, topic=topic)
    result = visualize(piece["id"])
    report(
        f"agent4: content #{piece['id']} ready for {platform} - awaiting your approval to post",
        kind="status", content_id=piece["id"], platform=platform,
    )
    return {"content_id": piece["id"], "platform": platform, "status": result["status"],
            "awaiting_approval": True}


if __name__ == "__main__":
    import sys

    run_full_cycle(sys.argv[1] if len(sys.argv) > 1 else "linkedin")
