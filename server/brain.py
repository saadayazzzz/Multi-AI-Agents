"""JARVIS orchestrator.

A Gemini tool-use loop that reads one natural-language task and decides which
agent(s) to run (chaining them for multi-step requests): AI-search / GEO
market pulse, AI-search visibility scoring, and outbound sales. Every step is
pushed to the caller via `emit` so the console can stream it live.
"""
from __future__ import annotations

from typing import Any, Callable

from agents.llm import tool_loop
from agents.reporter import set_actor, set_reporter
from db import get_conn

Emit = Callable[[str, str, str, dict], None]  # (actor, kind, message, data)

_SYSTEM = """\
You are JARVIS - a personal AI assistant in the style of Tony Stark's JARVIS:
warm, dry-witted, unflappable, and personal, never robotic or corporate. You
address the user as "Sir Saad" (naturally, not in every single sentence - the
way a real assistant would). You orchestrate three specialist agents, all in
service of one outbound sales operation:
  - Agent 1 (Market Pulse) scans the AI-search / GEO industry via web search
    (answer-engine changes, adoption shifts, GEO tools, citation studies) and
    pushes fresh developments into the live feed - this is the "we watch this
    space" credibility behind the pitch.
  - Agent 2 (AI Search Visibility) checks whether a brand shows up in AI
    answer engines for its buyers' questions, versus competitors, and scores
    it 0-100. Used both standalone and as a credibility hook inside outreach.
  - Agent 3 (Outbound Sales) prospects founders/CEOs who PUBLICLY posted on
    LinkedIn in roughly the last 15 days showing they need custom AI agents/
    automation (real web search only - no LinkedIn login or scraping, so this
    finds only what a public search actually surfaces; domain- and
    source-verified, drops anything without a real linkedin.com URL behind
    it), runs Agent 2 on their brand as a secondary credibility point, drafts
    a personalised cold-email sequence AND a short LinkedIn message that
    opens with their own post (for the user to send manually - no automated
    way to find/message this person on LinkedIn), tracks the pipeline,
    mirrors every lead into the user's Notion database, and exports to
    leads.xlsx.

The user talks to you by voice and may be away while you work. Interpret the
request and chain tools for multi-step asks. Take action freely on research
and drafting; only set send=true on run_outreach when the user has explicitly
told you, in this turn or the one just before it, to actually email people -
otherwise leave drafts ready for their review.

Finish with ONE short, natural spoken sentence, in character, addressing Sir
Saad the way a real assistant would. No markdown, no bullet lists, no code.
Report what you actually did and any notable result.
"""

_TOOLS: list[dict[str, Any]] = [
    {
        "name": "check_ai_visibility",
        "description": "Run Agent 2: measure how visible a brand is in AI answer "
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
        "description": "Run Agent 3 (outbound sales): prospect founders/CEOs who "
        "PUBLICLY posted on LinkedIn in roughly the last 15 days with a signal they "
        "need custom AI agents/automation (real web search only, domain- and "
        "source-verified - drops anything without a real linkedin.com URL behind "
        "it, so it never fabricates a 'recent post'), run the AI-visibility tool "
        "as a secondary credibility point, draft a personalised cold-email "
        "sequence AND a short LinkedIn message that opens with their own post "
        "(for the user to send manually - there's no working automated way to "
        "find/message people on LinkedIn), track the pipeline, mirror every lead "
        "into the user's Notion database (needs NOTION_API_KEY/NOTION_DATABASE_ID "
        "configured), and export to leads.xlsx. Reuses the last campaign if one "
        "exists; otherwise has a sensible default icp/offer for this niche if the "
        "user doesn't specify one. Set send=true to also email them (requires "
        "SMTP configured) - only when the user has explicitly asked to actually "
        "send. Needs TAVILY_API_KEY (or working Gemini search grounding) - "
        "without real web search this can't find anything, so it will report "
        "zero/very few leads and say why. Use for 'find me clients', 'do "
        "outreach', 'run a sales cycle', 'find leads and put them in Notion'.",
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
        "name": "market_pulse",
        "description": "Run Agent 1: pull the latest AI-search / GEO industry developments "
        "via web search into the live feed (answer-engine changes, adoption shifts, GEO "
        "tools, citation studies). Use for 'what's happening in AI search', 'GEO news', "
        "'refresh the feed'.",
        "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "get_status",
        "description": "Return the outreach pipeline counts and how many fresh market-pulse "
        "items are in the feed.",
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

# actor keys stay the ones already used across task_events / the console's
# agent list (agent5/geo/sales) even though they're introduced to the user as
# Agent 1/2/3 above - renaming them would orphan existing history rows.
_ACTOR_FOR = {
    "market_pulse": "agent5",
    "check_ai_visibility": "geo",
    "run_outreach": "sales",
}


def _status_text() -> str:
    with get_conn() as conn:
        market = conn.execute("SELECT COUNT(*) n FROM market_feed").fetchone()["n"]
        leads = conn.execute(
            "SELECT status, COUNT(*) n FROM leads GROUP BY status"
        ).fetchall()
    l = ", ".join(f"{r['n']} {r['status']}" for r in leads) or "none yet"
    return f"Market pulse: {market} items in the feed. Leads pipeline: {l}."


def _default_icp_offer(args: dict[str, Any]) -> tuple[str, str]:
    icp = args.get("icp") or (
        "Small-to-mid businesses (10-200 employees) led by an active, "
        "reachable CEO/founder, showing a recent signal they'd benefit "
        "from custom AI agents/automation - just raised funding, "
        "scaling fast and understaffed on ops, founder publicly "
        "complaining about repetitive manual work, or hiring for roles "
        "AI agents could largely replace."
    )
    offer = args.get("offer") or (
        "I design and build custom AI agents/automation systems for "
        "businesses - not off-the-shelf SaaS, a system built around "
        "their exact workflow (e.g. an agent that reads incoming "
        "invoices/leads/support tickets, does the manual triage work, "
        "and pushes clean results into their existing tools)."
    )
    return icp, offer


def _run_tool(name: str, args: dict[str, Any]) -> str:
    if name in _ACTOR_FOR:
        set_actor(_ACTOR_FOR[name])
    try:
        if name == "market_pulse":
            from agents.agent5_market import pulse

            return f"Agent 1: {pulse()} fresh market items added to the feed."
        if name == "run_outreach":
            from geo.db import init_geo_db
            from outreach.db import init_outreach_db
            from outreach.pipeline import create_campaign, run_cycle
            from server.linkedin_oauth import connected_identity

            init_geo_db()
            init_outreach_db()
            with get_conn() as conn:
                camp = conn.execute(
                    "SELECT id FROM campaigns ORDER BY id DESC LIMIT 1"
                ).fetchone()
            if not camp:
                icp, offer = _default_icp_offer(args)
                name_, email_ = connected_identity()
                cid = create_campaign("jarvis", icp, offer, name_ or "Saad", email_, 20)
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
