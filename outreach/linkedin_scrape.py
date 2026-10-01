"""Real-time LinkedIn lead signals via the user's own logged-in session.

This is a deliberate, explicit exception to the rest of this codebase's
"public web search only, no LinkedIn automation" design (see prospect.py's
docstring). The user chose this path knowing the tradeoff: it reads
LinkedIn's content-search UI (sorted by "Latest") as their own logged-in
account, which is real automation of LinkedIn and against its Terms of
Service. LinkedIn's bot detection WILL eventually flag sustained use of
this - that's a "when", not an "if". It is read-only (search + scroll +
extract text) - this module never connects, messages, likes, or comments
as the user, which somewhat reduces (does not eliminate) detection risk
versus write-automation.

Implementation: the actual browser automation lives in
linkedin_scraper/scrape.js (Node + playwright-core against the system
Chrome install, same approach already used elsewhere in this project for
headless screenshots) - Python's own playwright package needs a ~40MB
browser-driver wheel this environment couldn't reliably download, while
playwright-core (Node) was already installed and working. This module is
just a thin subprocess wrapper so the rest of the outreach pipeline stays
in Python.

Session handling: this never touches or stores the account password. A
one-time interactive login (`capture_session()`) opens a real visible
Chrome window, the user logs in by hand (including any 2FA/checkpoint),
and only the resulting session cookies are saved locally to
`linkedin_scraper/session.json` (gitignored - never commit this file, it's
equivalent to a password). Every later call reuses that saved session.

Why this actually solves the recency problem prospect.py's Tavily/Google
path can't: LinkedIn's own search UI shows an exact "Sort by: Latest" and
real relative timestamps ("2h", "1d") for content only its own logged-in
users can see ranked that way - a generic web search index only surfaces
LinkedIn posts that first accumulated enough external engagement/backlinks
to get crawled, which structurally biases it toward older posts.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

_DIR = Path(__file__).parent / "linkedin_scraper"
_SESSION_PATH = _DIR / "session.json"
_SCRIPT = _DIR / "scrape.js"
_NODE_MODULES = _DIR / "node_modules"


def has_session() -> bool:
    return _SESSION_PATH.exists()


def _run_node(args: list[str], timeout: int) -> subprocess.CompletedProcess:
    if not _NODE_MODULES.exists():
        raise RuntimeError(
            f"playwright-core not installed under {_NODE_MODULES} - "
            f"run `npm install playwright-core` there first."
        )
    return subprocess.run(
        ["node", str(_SCRIPT), *args],
        cwd=str(_DIR),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
    )


def capture_session(timeout_s: int = 320) -> bool:
    """Open a real, visible Chrome window for the user to log into LinkedIn
    by hand. Blocks until either login succeeds (feed loads) or timeout_s
    elapses. Returns True and saves the session on success."""
    try:
        r = _run_node(["--login"], timeout=timeout_s)
    except subprocess.TimeoutExpired:
        return False
    return r.returncode == 0 and has_session()


def search_recent_posts(query: str, max_posts: int = 15) -> list[dict]:
    """Search LinkedIn's own content search, sorted by Latest, using the
    saved session. Returns real posts with an author name/profile url, the
    post text, the post's own permalink, and (when decodable) its exact
    real timestamp - not an LLM guess."""
    if not has_session():
        raise RuntimeError(
            "No saved LinkedIn session - call capture_session() once first."
        )
    r = _run_node([query, str(max_posts)], timeout=150)
    if r.returncode == 2:
        raise RuntimeError("No saved LinkedIn session (session.json missing).")
    if r.returncode != 0:
        raise RuntimeError(f"LinkedIn scrape failed: {r.stderr.strip()[:500]}")
    try:
        return json.loads(r.stdout.strip() or "[]")
    except json.JSONDecodeError as e:
        raise RuntimeError(f"LinkedIn scrape returned bad JSON: {e}") from e


if __name__ == "__main__":
    import sys

    if "--login" in sys.argv:
        ok = capture_session()
        print("Session saved." if ok else "Login timed out / not detected.")
    else:
        q = sys.argv[1] if len(sys.argv) > 1 else "founder hiring is chaos"
        results = search_recent_posts(q, max_posts=10)
        print(json.dumps(results, indent=2, ensure_ascii=False))
