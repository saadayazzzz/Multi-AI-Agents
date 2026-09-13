"""Per-platform posting clients.

Each module exposes `post(content: dict, image_path: str | None) -> dict`
returning `{"id": ..., "url": ...}`, and raises a plain RuntimeError naming
the exact missing .env var when credentials aren't configured yet.
"""
from __future__ import annotations

from config import settings


def require(env_name: str, value: str, platform: str) -> str:
    if not value:
        raise RuntimeError(f"{env_name} is not set - add it to .env to enable {platform} posting")
    return value


__all__ = ["require", "settings"]
