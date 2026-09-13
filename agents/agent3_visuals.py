"""Agent 3 - Visual Studio.

Generates one thumbnail/cover image per content piece from Agent 2's
thumbnail_prompt, saves it to disk, and marks the content piece ready.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from agents.llm import PROVIDER, generate_image
from agents.reporter import report
from config import settings
from db import get_conn


def _load_content(conn, content_id: int | None) -> dict[str, Any] | None:
    if content_id:
        return conn.execute(
            "SELECT * FROM content_pieces WHERE id = %s", (content_id,)
        ).fetchone()
    return conn.execute(
        """
        SELECT c.* FROM content_pieces c
        LEFT JOIN content_images i ON i.content_id = c.id
        WHERE c.status = 'draft' AND i.id IS NULL
        ORDER BY c.created_at ASC LIMIT 1
        """
    ).fetchone()


def visualize(content_id: int | None = None) -> dict[str, Any]:
    img_dir = Path(settings.output_dir) / "content"
    img_dir.mkdir(parents=True, exist_ok=True)

    with get_conn() as conn:
        content = _load_content(conn, content_id)
        if not content:
            raise SystemExit("agent3: no draft content without an image found")

        extra = content.get("extra") or {}
        prompt = extra.get("thumbnail_prompt") or f"Eye-catching cover image for: {content['title']}"

        try:
            data = generate_image(prompt, size=settings.image_size)
            ext = "jpg" if data[:3] == b"\xff\xd8\xff" else "png"
            out = img_dir / f"{content['id']}.{ext}"
            out.write_bytes(data)
            rel_path = f"/img/content/{content['id']}.{ext}"
            kind = "photo"
            new_status = "ready"
            report(f"agent3: image for content #{content['id']} -> {rel_path} (via {PROVIDER})")
        except Exception as e:  # noqa: BLE001
            rel_path = None
            kind = "placeholder"
            # Instagram can't post without a real image; other platforms can
            # still go out as text-only, so only Instagram is blocked here.
            new_status = "draft" if content["platform"] == "instagram" else "ready"
            report(f"agent3: image failed for content #{content['id']} ({e})", kind="error")

        conn.execute(
            """
            INSERT INTO content_images (content_id, prompt, rel_path, kind)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (content_id) DO UPDATE SET
                prompt = EXCLUDED.prompt, rel_path = EXCLUDED.rel_path,
                kind = EXCLUDED.kind, created_at = now()
            """,
            (content["id"], prompt, rel_path, kind),
        )
        conn.execute(
            "UPDATE content_pieces SET status = %s, "
            "error = %s WHERE id = %s",
            (new_status, None if rel_path else "image generation failed", content["id"]),
        )

    return {"content_id": content["id"], "rel_path": rel_path, "status": new_status}


if __name__ == "__main__":
    from db import init_db

    init_db()
    visualize()
