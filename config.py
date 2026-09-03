"""Central configuration, loaded from environment / .env."""
from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


def _bool(name: str, default: bool) -> bool:
    return os.getenv(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    # Which model backend to use: "openai" or "anthropic".
    llm_provider: str = os.getenv("LLM_PROVIDER", "openai")

    # Claude API. If empty, the anthropic SDK resolves credentials from the
    # environment or an `ant auth login` profile. Accepts a real key or a
    # `claude setup-token` OAuth token (sk-ant-oat...).
    anthropic_api_key: str = os.getenv("ANTHROPIC_API_KEY", "")
    model: str = os.getenv("MODEL", "claude-opus-5")

    # OpenAI API.
    openai_api_key: str = os.getenv("OPENAI_API_KEY", "")
    openai_model: str = os.getenv("OPENAI_MODEL", "gpt-4.1")
    openai_image_model: str = os.getenv("OPENAI_IMAGE_MODEL", "gpt-image-1")
    image_size: str = os.getenv("IMAGE_SIZE", "1024x1024")
    max_images: int = int(os.getenv("MAX_IMAGES", "24"))

    database_url: str = os.getenv(
        "DATABASE_URL", "postgresql://maai:maai@localhost:5432/maai"
    )

    user_agent: str = os.getenv(
        "SCRAPER_USER_AGENT",
        "MultiAgentAI-Research/0.1 (+contact: you@example.com)",
    )
    scrape_delay_seconds: float = float(os.getenv("SCRAPE_DELAY_SECONDS", "2.0"))
    respect_robots: bool = _bool("RESPECT_ROBOTS", True)

    max_sites: int = int(os.getenv("MAX_SITES", "8"))
    max_pages_per_site: int = int(os.getenv("MAX_PAGES_PER_SITE", "12"))
    output_dir: str = os.getenv("OUTPUT_DIR", "output")

    # Control plane (FastAPI server + autonomous worker)
    server_host: str = os.getenv("SERVER_HOST", "127.0.0.1")
    server_port: int = int(os.getenv("SERVER_PORT", "8000"))
    worker_poll_seconds: float = float(os.getenv("WORKER_POLL_SECONDS", "2.0"))
    cors_origins: str = os.getenv(
        "CORS_ORIGINS",
        "http://localhost:3737,http://127.0.0.1:3737",
    )


settings = Settings()
