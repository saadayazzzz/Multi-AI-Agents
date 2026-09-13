"""JARVIS orchestrator.

A Gemini tool-use loop that reads one natural-language task, decides which of
the four content-marketing agents to run (chaining them for multi-step
requests), and returns a short spoken response. Every step is pushed to the
caller via `emit` so the console can stream it live.
"""
from __future__ import annotations

from typing import Any, Callable

from agents.agent1_trends import scout
from agents.agent2_content import write
from agents.agent3_visuals import visualize
from agents.agent4_publisher import publish, run_full_cycle
from agents.llm import tool_loop
from agents.reporter import set_actor, set_reporter
from db import get_conn

Emit = Callable[[str, str, str, dict], None]  # (actor, kind, message, data)

_SYSTEM = """\
You are JARVIS - a personal AI assistant in the style of Tony Stark's JARVIS:
warm, dry-witted, unflappable, and personal, never robotic or corporate. You
address the user as "Sir Saad" (naturally, not in every single sentence - the
way a real assistant would). You are also the orchestrator of a four-agent
autonomous content-marketing team:
  - Agent 1 (Trend Scout) researches what's trending right now on YouTube,
    Instagram, and LinkedIn.
  - Agent 2 (Content Studio) writes a platform-native script/caption/hashtags/
    CTA for a trend or topic.
  - Agent 3 (Visual Studio) generates a thumbnail/cover image for a piece of
    content.
  - Agent 4 (Publisher) posts finished content live to its platform.

IMPORTANT - approval gate: nothing is ever posted without the user's explicit
go-ahead in this conversation. `run_full_cycle` only researches, writes, and
generates the thumbnail - it stops at "ready" and never posts. Only call
`publish_content` when the user has explicitly told you, in this turn or the
one just before it, to post/approve/publish that specific piece (e.g. "post
it", "yes go ahead", "approve content 5", "publish that"). If a request asks
you to create AND post in one breath (e.g. "make a post about X and publish
it"), still do NOT call publish_content - prepare the content, tell them it's
ready, and wait for their explicit approval before posting anything.

The user talks to you by voice and may be away while you work. Interpret the
request and chain tools for multi-step asks (e.g. "write something for
LinkedIn about X" = write_content -> generate_thumbnail, then report back and
wait). Take action on research/writing/visuals freely - only posting needs
their sign-off.

Finish with ONE short, natural spoken sentence, in character, addressing Sir
Saad the way a real assistant would. No markdown, no bullet lists, no code.
Report what you actually did and any notable result.
"""

_TOOLS: list[dict[str, Any]] = [
    {
        "name": "find_trends",
        "description": "Run Agent 1: research trending topics/formats for one "
        "platform, or all three (youtube/instagram/linkedin) if omitted.",
        "input_schema": {
            "type": "object",
            "properties": {"platform": {"type": "string", "enum": ["youtube", "instagram", "linkedin"]}},
            "additionalProperties": False,
        },
    },
    {
        "name": "write_content",
        "description": "Run Agent 2: write a script/caption/hashtags/CTA for a "
        "platform, from a specific topic or the top unused trend.",
        "input_schema": {
            "type": "object",
            "properties": {
                "platform": {"type": "string", "enum": ["youtube", "instagram", "linkedin"]},
                "topic": {"type": "string"},
            },
            "required": ["platform"],
            "additionalProperties": False,
        },
    },
    {
        "name": "generate_thumbnail",
        "description": "Run Agent 3: generate a cover image/thumbnail for a "
        "piece of content.",
        "input_schema": {
            "type": "object",
            "properties": {"content_id": {"type": "integer"}},
            "required": ["content_id"],
            "additionalProperties": False,
        },
    },
    {
        "name": "publish_content",
        "description": "Run Agent 4: post a finished piece of content to its "
        "platform right now. ONLY call this when the user has explicitly "
        "approved posting this specific content in this conversation - never "
        "call it proactively or as an automatic last step of content creation. "
        "Omit content_id for a plain 'post it' approval - it resolves to the "
        "most recently prepared piece awaiting approval.",
        "input_schema": {
            "type": "object",
            "properties": {"content_id": {"type": "integer"}},
            "additionalProperties": False,
        },
    },
    {
        "name": "run_full_cycle",
        "description": "Find a trend (or use the given topic), write it, and "
        "generate its thumbnail for one platform. Stops at 'ready' - does NOT "
        "publish. Use publish_content separately once the user approves.",
        "input_schema": {
            "type": "object",
            "properties": {
                "platform": {"type": "string", "enum": ["youtube", "instagram", "linkedin"]},
                "topic": {"type": "string"},
            },
            "required": ["platform"],
            "additionalProperties": False,
        },
    },
    {
        "name": "get_status",
        "description": "Return counts of trends, drafted content, and posts "
        "published per platform.",
        "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "schedule_recurring",
        "description": "Create a recurring task the worker runs on an interval, "
        "even while the user is away. Use for 'keep doing X every N minutes'.",
        "input_schema": {
            "type": "object",
            "properties": {
                "prompt": {"type": "string", "description": "the instruction to repeat"},
                "every_minutes": {"type": "integer", "minimum": 5},
            },
            "required": ["prompt", "every_minutes"],
            "additionalProperties": False,
        },
    },
]

_ACTOR_FOR = {
    "find_trends": "agent1",
    "write_content": "agent2",
    "generate_thumbnail": "agent3",
    "publish_content": "agent4",
    "run_full_cycle": "agent4",
}


def _status_text() -> str:
    with get_conn() as conn:
        trends = conn.execute(
            "SELECT platform, COUNT(*) n FROM trends WHERE status='new' GROUP BY platform"
        ).fetchall()
        content = conn.execute(
            "SELECT status, COUNT(*) n FROM content_pieces GROUP BY status"
        ).fetchall()
        posted = conn.execute(
            "SELECT platform, COUNT(*) n FROM content_pieces WHERE status='posted' GROUP BY platform"
        ).fetchall()
    t = ", ".join(f"{r['n']} {r['platform']}" for r in trends) or "none"
    c = ", ".join(f"{r['n']} {r['status']}" for r in content) or "none"
    p = ", ".join(f"{r['n']} {r['platform']}" for r in posted) or "none"
    return f"Unused trends: {t}. Content by status: {c}. Posted: {p}."


def _run_tool(name: str, args: dict[str, Any]) -> str:
    if name in _ACTOR_FOR:
        set_actor(_ACTOR_FOR[name])
    try:
        if name == "find_trends":
            rows = scout(args.get("platform"))
            return f"Found {len(rows)} trends: " + ", ".join(r["topic"] for r in rows[:10])
        if name == "write_content":
            row = write(args["platform"], topic=args.get("topic"))
            return f"Drafted content #{row['id']} for {row['platform']}: {row['title']}"
        if name == "generate_thumbnail":
            r = visualize(args["content_id"])
            return f"Thumbnail for content #{r['content_id']}: {r['status']}"
        if name == "publish_content":
            r = publish(args.get("content_id"))
            return f"Content #{r['content_id']}: {r['status']}" + (f" ({r['error']})" if r.get("error") else "")
        if name == "run_full_cycle":
            r = run_full_cycle(args["platform"], topic=args.get("topic"))
            return (f"Content #{r['content_id']} for {args['platform']} is {r['status']} - "
                    f"awaiting your approval to post.")
        if name == "get_status":
            return _status_text()
        if name == "schedule_recurring":
            secs = max(300, int(args["every_minutes"]) * 60)
            with get_conn() as conn:
                conn.execute(
                    "INSERT INTO tasks (prompt, source, recur_seconds, run_after) "
                    "VALUES (%s, 'schedule', %s, now() + (%s || ' seconds')::interval)",
                    (args["prompt"], secs, secs),
                )
            return f"Scheduled '{args['prompt']}' every {secs // 60} minutes."
        return f"Unknown tool: {name}"
    finally:
        set_actor("orchestrator")


def _execute(name: str, args: dict[str, Any]) -> tuple[str, bool]:
    try:
        return _run_tool(name, args or {}), False
    except Exception as e:  # noqa: BLE001
        return f"Error: {e}", True


def run_task(task_id: int, prompt: str, emit: Emit) -> tuple[str, str]:
    """Execute one task. Returns (result_summary, spoken_response)."""
    set_reporter(lambda actor, kind, msg, data: emit(actor, kind, msg, data), actor="orchestrator")
    try:
        spoken, steps = tool_loop(_SYSTEM, prompt, _TOOLS, _execute, emit, max_iters=20)
    finally:
        set_reporter(None)

    summary = " | ".join(steps) if steps else spoken
    return summary[:4000], (spoken or "Done.")
