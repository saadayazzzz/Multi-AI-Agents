"""Polite HTTP fetching: robots.txt aware, rate limited, identifies itself.

This project is for research/analysis. Keep the delay conservative, keep
RESPECT_ROBOTS on, and set a real contact string in SCRAPER_USER_AGENT.
"""
from __future__ import annotations

import time
import urllib.robotparser
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

from agents.reporter import report
from config import settings

_STRIP_TAGS = ["script", "style", "noscript", "svg", "template", "iframe"]
_CHROME_TAGS = ["header", "footer", "nav", "form"]


class PoliteFetcher:
    def __init__(self, delay: float | None = None, user_agent: str | None = None):
        self.delay = delay if delay is not None else settings.scrape_delay_seconds
        self.ua = user_agent or settings.user_agent
        self._last = 0.0
        self._robots: dict[str, urllib.robotparser.RobotFileParser | None] = {}
        self.client = httpx.Client(
            headers={"User-Agent": self.ua, "Accept": "text/html"},
            follow_redirects=True,
            timeout=20.0,
        )

    # -- robots ----------------------------------------------------------------
    def _robots_for(self, url: str):
        p = urlparse(url)
        base = f"{p.scheme}://{p.netloc}"
        if base not in self._robots:
            rp = urllib.robotparser.RobotFileParser()
            rp.set_url(urljoin(base, "/robots.txt"))
            try:
                rp.read()
            except Exception:
                rp = None
            self._robots[base] = rp
        return self._robots[base]

    def allowed(self, url: str) -> bool:
        if not settings.respect_robots:
            return True
        rp = self._robots_for(url)
        return True if rp is None else rp.can_fetch(self.ua, url)

    # -- fetching ------------------------------------------------------------
    def _throttle(self) -> None:
        wait = self.delay - (time.monotonic() - self._last)
        if wait > 0:
            time.sleep(wait)
        self._last = time.monotonic()

    def get(self, url: str) -> httpx.Response | None:
        """Return the response, or None if disallowed / failed / not HTML."""
        if not self.allowed(url):
            report(f"robots.txt disallows {url}")
            return None
        self._throttle()
        try:
            r = self.client.get(url)
        except httpx.HTTPError as e:
            report(f"fetch error {url}: {e}")
            return None
        if "html" not in r.headers.get("content-type", ""):
            return None
        return r

    def get_json(self, url: str):
        """Fetch a JSON endpoint (e.g. Shopify /products.json). None on any failure."""
        if not self.allowed(url):
            return None
        self._throttle()
        try:
            r = self.client.get(url)
            if r.status_code == 200 and "json" in r.headers.get("content-type", ""):
                return r.json()
        except (httpx.HTTPError, ValueError):
            return None
        return None

    def close(self) -> None:
        self.client.close()

    def __enter__(self) -> "PoliteFetcher":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # -- parsing ------------------------------------------------------------
    @staticmethod
    def clean_text(html: str, max_chars: int = 14000) -> str:
        soup = BeautifulSoup(html, "html.parser")
        for tag in soup(_STRIP_TAGS + _CHROME_TAGS):
            tag.decompose()
        text = " ".join(soup.get_text(" ").split())
        return text[:max_chars]

    @staticmethod
    def same_host(a: str, b: str) -> bool:
        return urlparse(a).netloc.lstrip("www.") == urlparse(b).netloc.lstrip("www.")

    @classmethod
    def find_links(cls, html: str, base_url: str, keywords: tuple[str, ...]) -> list[str]:
        """On-site links whose URL contains any of `keywords`, de-duplicated."""
        soup = BeautifulSoup(html, "html.parser")
        seen: set[str] = set()
        out: list[str] = []
        for a in soup.find_all("a", href=True):
            href = urljoin(base_url, a["href"]).split("#")[0].split("?")[0].rstrip("/")
            if not href.startswith("http") or not cls.same_host(href, base_url):
                continue
            low = href.lower()
            if any(k in low for k in keywords) and href not in seen:
                seen.add(href)
                out.append(href)
        return out
