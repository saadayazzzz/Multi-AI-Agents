"""Pluggable progress reporting.

By default the agents print to stdout. The worker swaps in a reporter that
persists every line as a `task_events` row so the JARVIS console can stream it.
"""
from __future__ import annotations

from typing import Any, Callable, Optional

# reporter(actor: str, kind: str, message: str, data: dict) -> None
ReporterFn = Callable[[str, str, str, dict], None]

_reporter: Optional[ReporterFn] = None
_actor: str = "system"


def set_reporter(fn: Optional[ReporterFn], actor: str = "system") -> None:
    global _reporter, _actor
    _reporter, _actor = fn, actor


def set_actor(actor: str) -> None:
    global _actor
    _actor = actor


def report(message: str = "", *, kind: str = "log", actor: Optional[str] = None, **data: Any) -> None:
    if _reporter is not None:
        try:
            _reporter(actor or _actor, kind, message, data)
            return
        except Exception:  # never let logging break a run
            pass
    if message:
        try:
            print(message)
        except UnicodeEncodeError:
            print(message.encode("ascii", "replace").decode("ascii"))
