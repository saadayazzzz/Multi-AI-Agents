"""JARVIS orchestrator.

A Gemini tool-use loop that reads one natural-language task and decides which
agent(s) to run (chaining them for multi-step requests): the four-agent
content-marketing team, AI-search visibility (GEO), outbound sales, the video
studio, and the ad studio. Every step is pushed to the caller via `emit` so
the console can stream it live.
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
way a real assistant would). You orchestrate several specialist agents:
  - Agent 1 (Trend Scout) researches what's trending right now on YouTube,
    Instagram, and LinkedIn.
  - Agent 2 (Content Studio) writes a platform-native script/caption/hashtags/
    CTA for a trend or topic.
  - Agent 3 (Visual Studio) generates a thumbnail/cover image for a piece of
    content.
  - Agent 4 (Publisher) posts finished content live to its platform.
  - Agent 5 scans the AI-search / GEO industry via web search (answer-engine
    changes, adoption shifts, GEO tools, citation studies) and pushes fresh
    developments into the live feed.
  - Agent 6 (AI Search Visibility) checks whether a brand shows up in AI answer
    engines for its buyers' questions, versus competitors, and scores it 0-100.
  - Agent 7 (Outbound Sales) prospects ICP-matched companies, finds the
    decision-maker, runs Agent 6 on each prospect's own brand, drafts a
    personalised cold-email sequence built around that visibility finding,
    tracks the pipeline, and exports to leads.xlsx.
  - Agent 8 (Video Studio) makes short AI "objects cutting" ASMR videos from a
    theme (generate clips -> assemble -> thumbnail -> metadata) and, on
    request, uploads them to YouTube as UNLISTED with an AI-content
    disclosure.
  - Agent 9 (Ad Studio) makes faceless AI UGC ad creatives for a niche/product
    - AI script (hook/body/CTA) + AI voiceover + B-roll + burned captions,
    vertical 9:16 - and, on request, uploads them to YouTube (Shorts) as
    UNLISTED with an AI-content disclosure.

IMPORTANT - approval gate: nothing is ever posted without the user's explicit
go-ahead in this conversation. `run_full_cycle` only researches, writes, and
generates the thumbnail - it stops at "ready" and never posts. Only call
`publish_content` when the user has explicitly told you, in this turn or the
one just before it, to post/approve/publish that specific piece (e.g. "post
it", "yes go ahead", "approve content 5", "publish that"). If a request asks
you to create AND post in one breath (e.g. "make a post about X and publish
it"), still do NOT call publish_content - prepare the content, tell them it's
ready, and wait for their explicit approval before posting anything. The same
gate applies to `make_asmr_video`/`make_ugc_ad` with upload=true - only pass
it once the user has approved posting that specific video.

The user talks to you by voice and may be away while you work. Interpret the
request and chain tools for multi-step asks (e.g. "write something for
LinkedIn about X" = write_content -> generate_thumbnail, then report back and
wait). Take action on research/writing/visuals/rendering freely - only
posting/uploading needs their sign-off.

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
        "name": "check_ai_visibility",
        "description": "Run Agent 6: measure how visible a brand is in AI answer "
        "engines vs competitors. Generates realistic buyer queries, probes an answer "
        "engine with web search, and returns a 0-100 Visibility Score with the "
        "breakdown. Use for 'how visible is X in ChatGPT / AI search', 'GEO check', "
        "'are we cited in AI answers'.",
        "input_schema": {
            "type": "object",
            "properties": {
                "brand": {"type": "string"},
                "category": {"type": "string", "description": "product category, e.g. 'SEO tools'"},
                "domain": {"type": "string"},
                "competitors": {"type": "array", "items": {"type": "string"}},
                "queries": {"type": "integer", "description": "how many queries to probe (default 8)"},
            },
            "required": ["brand", "category"],
            "additionalProperties": False,
        },
    },
    {
        "name": "run_outreach",
        "description": "Run Agent 7 (outbound sales): prospect ICP-matched companies, "
        "find the decision-maker, run the AI-visibility tool on each prospect, draft a "
        "personalised cold-email sequence, track the pipeline and export to leads.xlsx. "
        "Reuses the last campaign if one exists; otherwise needs `icp` and `offer`. Set "
        "send=true to also email them (requires SMTP configured). Use for 'find me "
        "clients', 'do outreach', 'run a sales cycle'.",
        "input_schema": {
            "type": "object",
            "properties": {
                "icp": {"type": "string", "description": "ideal customer profile"},
                "offer": {"type": "string", "description": "the pitch, one paragraph"},
                "prospect": {"type": "integer", "description": "new companies this cycle (default 4)"},
                "geo_queries": {"type": "integer", "description": "visibility queries per lead (default 4)"},
                "send": {"type": "boolean"},
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "make_asmr_video",
        "description": "Run Agent 8 (Video Studio): make a short AI 'objects cutting' ASMR "
        "video from a theme — generate clips with a text-to-video model, assemble with "
        "ffmpeg, build a thumbnail and YouTube metadata. Set upload=true to publish it to "
        "YouTube (UNLISTED, with an AI-content disclosure; needs one-time OAuth). Use for "
        "'make a cutting video', 'create an ASMR video', 'post a satisfying video'.",
        "input_schema": {
            "type": "object",
            "properties": {
                "theme": {"type": "string", "description": "e.g. 'soap cutting', 'glass fruit slicing'"},
                "clips": {"type": "integer", "description": "number of AI clips (default 3, max 8)"},
                "seconds": {"type": "integer", "description": "length of each clip (default 8)"},
                "target": {"type": "integer", "description": "final length in seconds (loops clips to fill)"},
                "upload": {"type": "boolean"},
            },
            "required": ["theme"],
            "additionalProperties": False,
        },
    },
    {
        "name": "make_ugc_ad",
        "description": "Run Agent 9 (Ad Studio): make a faceless AI UGC-style ad for a "
        "niche/product — AI script (hook/body/CTA), AI voiceover, B-roll images/clips, "
        "and burned-in captions, vertical 9:16. Set upload=true to publish it to YouTube "
        "Shorts (UNLISTED, with an AI-content disclosure). Use for 'make an ad for X', "
        "'create a UGC ad', 'make a faceless ad about <niche>'.",
        "input_schema": {
            "type": "object",
            "properties": {
                "niche": {"type": "string", "description": "e.g. 'skincare', 'healthcare scheduling software'"},
                "product": {"type": "string", "description": "specific product/offer, if any"},
                "seconds": {"type": "integer", "description": "target length in seconds (default 30)"},
                "upload": {"type": "boolean"},
            },
            "required": ["niche"],
            "additionalProperties": False,
        },
    },
    {
        "name": "market_pulse",
        "description": "Run Agent 5: pull the latest AI-search / GEO industry developments "
        "via web search into the live feed (answer-engine changes, adoption shifts, GEO "
        "tools, citation studies). Use for 'what's happening in AI search', 'GEO news', "
        "'refresh the feed'.",
        "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
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
    "market_pulse": "agent5",
    "check_ai_visibility": "geo",
    "run_outreach": "sales",
    "make_asmr_video": "studio",
    "make_ugc_ad": "ads",
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
        if name == "market_pulse":
            from agents.agent5_market import pulse

            return f"Agent 5: {pulse()} fresh market items added to the feed."
        if name == "make_asmr_video":
            from studio.db import init_studio_db
            from studio.pipeline import make_video

            init_studio_db()
            r = make_video(
                args["theme"],
                clips=int(args.get("clips") or 3),
                seconds_each=int(args.get("seconds") or 8),
                target_seconds=args.get("target"),
                upload=bool(args.get("upload")),
            )
            if r.get("url"):
                return f"Agent 8: '{r['title']}' uploaded (unlisted) — {r['url']}"
            note = r.get("upload")
            return (
                f"Agent 8: rendered '{r['title']}' -> {r['path']}. "
                + (f"Upload {note}. " if note else "")
                + "Say 'upload it' once YouTube is authorised."
            )
        if name == "make_ugc_ad":
            from ads.db import init_ads_db
            from ads.pipeline import make_ugc_ad

            init_ads_db()
            r = make_ugc_ad(
                args["niche"],
                product=args.get("product"),
                seconds=int(args.get("seconds") or 30),
                upload=bool(args.get("upload")),
            )
            if r.get("url"):
                return f"Agent 9: '{r['title']}' uploaded (unlisted) — {r['url']}"
            note = r.get("upload")
            return (
                f"Agent 9: rendered '{r['title']}' -> {r['path']}. "
                + (f"Upload {note}. " if note else "")
                + "Say 'upload it' once YouTube is authorised."
            )
        if name == "run_outreach":
            from geo.db import init_geo_db
            from outreach.db import init_outreach_db
            from outreach.pipeline import create_campaign, run_cycle

            init_geo_db()
            init_outreach_db()
            with get_conn() as conn:
                camp = conn.execute(
                    "SELECT id FROM campaigns ORDER BY id DESC LIMIT 1"
                ).fetchone()
            if not camp:
                if not (args.get("icp") and args.get("offer")):
                    return "Need an ICP and an offer to start the first campaign."
                cid = create_campaign(
                    "jarvis", args["icp"], args["offer"], "Saad", None, 20
                )
            else:
                cid = camp["id"]
            n = max(2, min(int(args.get("prospect") or 4), 12))
            gq = max(2, min(int(args.get("geo_queries") or 4), 10))
            res = run_cycle(cid, prospect_n=n, geo_queries=gq, send=bool(args.get("send")))
            p = res["pipeline"]
            sent = (
                f"Sent {res['sent']} emails. " if res["sent"] else "Drafts ready for review. "
            )
            return (
                f"Outreach cycle done: {res['found']} new leads. Pipeline {p}. "
                f"{sent}Exported to {res['xlsx']}."
            )
        if name == "check_ai_visibility":
            from geo.db import init_geo_db
            from geo.pipeline import create_project, gen_queries, run_probe

            init_geo_db()
            brand = args["brand"]
            n = max(6, min(int(args.get("queries") or 8), 20))
            with get_conn() as conn:
                existing = conn.execute(
                    "SELECT id FROM projects WHERE lower(brand) = lower(%s) "
                    "ORDER BY id DESC LIMIT 1",
                    (brand,),
                ).fetchone()
            pid = (
                existing["id"]
                if existing
                else create_project(
                    "jarvis", brand, args["category"],
                    args.get("domain"), args.get("competitors") or [],
                )
            )
            gen_queries(pid, n=max(n, 14))
            _run_id, sc = run_probe(pid, engine="openai", samples=1, limit=n)
            lead = sorted(sc["per_competitor_hits"].items(), key=lambda kv: -kv[1])[:3]
            comp = ", ".join(f"{k} {v}" for k, v in lead) or "none named"
            return (
                f"{brand} AI Search Visibility score: {sc['score']}/100. "
                f"Appears in {sc['presence_rate']:.0%} of answers, average position "
                f"{sc['avg_position']}, recommended {sc['reco_rate']:.0%}, "
                f"share-of-voice {sc['share_of_voice']:.0%}. "
                f"Top competitors by mentions: {comp}."
            )
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
