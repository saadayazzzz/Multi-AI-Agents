"""LinkedIn seats + the Python side of outreach/linkedin_scraper/linkedin.js.

A seat is one LinkedIn account, logged in once by hand (`login(seat_id)`
opens a real Chrome window); only the resulting session cookies are stored,
never the password.

READ modes (sourcing signals, inbox sync) run whenever a seat has a
session. WRITE modes (invite / message / like / visit / reply) are automated
LinkedIn activity, which LinkedIn's terms forbid and its detection does
catch eventually - so they only run on a seat whose `automation_enabled` is
true, and always inside that seat's daily caps (`take_quota`). With
automation off, the campaign executor turns every LinkedIn step into a
"manual" task with the drafted text, for the user to do by hand -
Gojiberry's own manual-campaign mode.
"""
from __future__ import annotations

import json
import subprocess
import tempfile
from datetime import date
from pathlib import Path
from typing import Any

from db.database import get_conn

_DIR = Path(__file__).resolve().parent.parent / "outreach" / "linkedin_scraper"
_SCRIPT = _DIR / "linkedin.js"
DEFAULT_SESSION = _DIR / "session.json"

READ_MODES = {
    "search_posts", "post_engagers", "profile_posts", "profile_views", "company_followers",
    "search_people", "search_events", "event_attendees", "search_groups", "group_posts",
    "search_jobs", "profile", "company", "inbox", "thread",
}
WRITE_MODES = {"invite", "message", "visit", "like_posts", "reply"}


class LinkedInError(RuntimeError):
    pass


class NoSession(LinkedInError):
    pass


class LoggedOut(LinkedInError):
    pass


class AutomationDisabled(LinkedInError):
    pass


# ------------------------------------------------------------------ seats --

_SEAT_FIELDS = [
    "name", "profile_url", "session_path", "sales_navigator", "automation_enabled",
    "daily_invitations", "daily_messages", "daily_visits", "daily_likes",
    "launch_hour", "active_days", "timezone",
]


def create_seat(**fields: Any) -> dict:
    cols = [c for c in _SEAT_FIELDS if fields.get(c) is not None]
    with get_conn() as conn:
        return conn.execute(
            f"INSERT INTO linkedin_seats ({', '.join(cols)}) VALUES ({', '.join(['%s'] * len(cols))}) RETURNING *",
            [fields[c] for c in cols],
        ).fetchone()


def update_seat(seat_id: int, **fields: Any) -> dict | None:
    sets = [(c, v) for c, v in fields.items() if c in _SEAT_FIELDS and v is not None]
    if sets:
        with get_conn() as conn:
            conn.execute(
                f"UPDATE linkedin_seats SET {', '.join(f'{c} = %s' for c, _ in sets)} WHERE id = %s",
                (*[v for _, v in sets], seat_id),
            )
    return get_seat(seat_id)


def get_seat(seat_id: int | None) -> dict | None:
    if seat_id is None:
        return None
    with get_conn() as conn:
        return conn.execute("SELECT * FROM linkedin_seats WHERE id = %s", (seat_id,)).fetchone()


def list_seats() -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM linkedin_seats ORDER BY id").fetchall()
    for r in rows:
        r["has_session"] = session_path(r).exists()
    return rows


def delete_seat(seat_id: int) -> None:
    with get_conn() as conn:
        conn.execute("DELETE FROM linkedin_seats WHERE id = %s", (seat_id,))


def default_seat() -> dict | None:
    with get_conn() as conn:
        return conn.execute("SELECT * FROM linkedin_seats ORDER BY id LIMIT 1").fetchone()


def session_path(seat: dict | None) -> Path:
    if seat and seat.get("session_path"):
        return Path(seat["session_path"])
    if seat:
        p = _DIR / f"session_seat{seat['id']}.json"
        # Seat 1 inherits the session the old scraper already captured.
        if not p.exists() and DEFAULT_SESSION.exists() and seat["id"] == (default_seat() or {}).get("id"):
            return DEFAULT_SESSION
        return p
    return DEFAULT_SESSION


def has_session(seat: dict | None = None) -> bool:
    return session_path(seat).exists()


# ----------------------------------------------------------------- quotas --

_QUOTA_COLUMN = {
    "invitation": "daily_invitations",
    "message": "daily_messages",
    "visit": "daily_visits",
    "like": "daily_likes",
}


def used_today(kind: str, seat_id: int, action: str, day: date | None = None) -> int:
    with get_conn() as conn:
        r = conn.execute(
            "SELECT count FROM seat_daily_usage WHERE seat_kind = %s AND seat_id = %s AND day = %s AND action = %s",
            (kind, seat_id, day or date.today(), action),
        ).fetchone()
    return r["count"] if r else 0


def take_quota(kind: str, seat_id: int, action: str, cap: int, day: date | None = None) -> bool:
    """Atomically count one action against today's cap. False = cap reached."""
    if cap <= 0:
        return False
    with get_conn() as conn:
        r = conn.execute(
            """
            INSERT INTO seat_daily_usage (seat_kind, seat_id, day, action, count)
            VALUES (%s, %s, %s, %s, 1)
            ON CONFLICT (seat_kind, seat_id, day, action)
            DO UPDATE SET count = seat_daily_usage.count + 1
            WHERE seat_daily_usage.count < %s
            RETURNING count
            """,
            (kind, seat_id, day or date.today(), action, cap),
        ).fetchone()
    return r is not None


def seat_cap(seat: dict, action: str) -> int:
    return int(seat.get(_QUOTA_COLUMN[action]) or 0)


# ----------------------------------------------------------------- bridge --


def call(mode: str, args: dict | None = None, seat: dict | None = None, timeout: int = 180,
         user_initiated: bool = False) -> Any:
    """Run one linkedin.js mode. `user_initiated` is only for a reply the
    user typed themselves in the unibox - never for campaign steps."""
    if user_initiated and mode != "reply":
        raise ValueError("user_initiated only applies to 'reply'")
    if mode in WRITE_MODES and not user_initiated and not (seat and seat.get("automation_enabled")):
        raise AutomationDisabled(f"LinkedIn automation is off for this seat - '{mode}' not sent")
    if mode not in READ_MODES | WRITE_MODES | {"login"}:
        raise ValueError(f"unknown LinkedIn mode {mode}")
    if not (_DIR / "node_modules").exists():
        raise LinkedInError(f"playwright-core missing - run `npm install` in {_DIR}")
    sp = session_path(seat)
    if mode != "login" and not sp.exists():
        raise NoSession("no LinkedIn session - log the seat in first")
    payload = dict(args or {})
    payload["session"] = str(sp)
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as f:
        json.dump(payload, f)
        argfile = f.name
    try:
        r = subprocess.run(
            ["node", str(_SCRIPT), mode, "@" + argfile],
            cwd=str(_DIR), capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=timeout,
        )
    except subprocess.TimeoutExpired as e:
        raise LinkedInError(f"LinkedIn '{mode}' timed out after {timeout}s") from e
    finally:
        Path(argfile).unlink(missing_ok=True)
    if r.returncode == 2:
        raise NoSession("no LinkedIn session file")
    if r.returncode == 3:
        raise LoggedOut(f"LinkedIn session expired ({r.stderr.strip()[:200]}) - log the seat in again")
    if r.returncode != 0:
        raise LinkedInError(f"LinkedIn '{mode}' failed: {r.stderr.strip()[:500]}")
    try:
        return json.loads(r.stdout.strip() or "null")
    except json.JSONDecodeError as e:
        raise LinkedInError(f"LinkedIn '{mode}' returned bad JSON: {e}") from e


def login(seat: dict | None, timeout_s: int = 320) -> bool:
    out = call("login", {"timeout_ms": (timeout_s - 20) * 1000}, seat, timeout=timeout_s)
    return (out or {}).get("status") == "saved"
