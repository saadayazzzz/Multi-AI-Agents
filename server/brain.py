"""JARVIS orchestrator.

A Claude tool-use loop that reads one natural-language task, decides which of the
three agents to run (chaining them for multi-step requests), and returns a short
spoken response. Every step is pushed to the caller via `emit` so the console can
stream it live.
"""
from __future__ import annotations

from typing import Any, Callable

from agents.agent1_discovery import discover
from agents.agent2_scraper import scrape
from agents.agent3_brand_builder import build
from agents.llm import tool_loop
from agents.reporter import set_actor, set_reporter
from db import get_conn

Emit = Callable[[str, str, str, dict], None]  # (actor, kind, message, data)

_SYSTEM = """\
You are JARVIS, the orchestrator of a four-agent beauty-commerce team:
  - Agent 1 discovers high-quality skincare / cosmetics websites.
  - Agent 2 scrapes product and brand data from those sites into a database.
  - Agent 3 designs a brand-new ORIGINAL brand from that data and generates a
    Next.js storefront on disk.
  - Agent 4 generates a product photo for each product in the built store and
    drops it into the site.
  - Agent 5 scans the AI-search / GEO industry via web search (answer-engine
    changes, adoption shifts, GEO tools, citation studies) and pushes fresh
    developments into the live feed.
  - Agent 6 (AI Search Visibility) checks whether a brand shows up in AI answer
    engines for its buyers' questions, versus competitors, and scores it 0-100.

The user talks to you by voice and may be away while you work. Interpret the
request, call whatever tools are needed, and chain them for multi-step asks
(e.g. "find fresh sites and rebuild the store with images" =
discover -> scrape -> build -> generate images). Prefer action over questions.

Finish with ONE short, natural spoken sentence. No markdown, no bullet lists,
no code. Report what you actually did and any notable result.
"""

_TOOLS: list[dict[str, Any]] = [
    {
        "name": "discover_sites",
        "description": "Run Agent 1: research the web and add high-quality skincare/"
        "cosmetics sites to the database.",
        "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "scrape_sites",
        "description": "Run Agent 2: crawl sites that have not been scraped yet and "
        "extract product + brand data into the database.",
        "input_schema": {
            "type": "object",
            "properties": {"limit": {"type": "integer", "description": "max sites this run"}},
            "additionalProperties": False,
        },
    },
    {
        "name": "build_brand",
        "description": "Run Agent 3: design a new original brand from the collected data "
        "and generate its Next.js storefront under output/. Set with_images to also run "
        "Agent 4 for product photos in the same pass.",
        "input_schema": {
            "type": "object",
            "properties": {
                "with_images": {"type": "boolean", "description": "also generate product photos"}
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "generate_product_images",
        "description": "Run Agent 4: generate a product photo for each product in the most "
        "recently built store (or a given brand slug) and place it in the site.",
        "input_schema": {
            "type": "object",
            "properties": {
                "slug": {"type": "string", "description": "brand slug; default = latest"},
                "limit": {"type": "integer", "description": "max images to generate"},
            },
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
        "name": "market_pulse",
        "description": "Run Agent 5: pull the latest AI-search / GEO industry developments "
        "via web search into the live feed (answer-engine changes, adoption shifts, GEO "
        "tools, citation studies). Use for 'what's happening in AI search', 'GEO news', "
        "'refresh the feed'.",
        "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "get_status",
        "description": "Return counts of sites (by status), products, and generated brands.",
        "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "schedule_recurring",
        "description": "Create a recurring task the worker runs on an interval, even while "
        "the user is away. Use for 'keep doing X every N minutes' requests.",
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
    "discover_sites": "agent1",
    "scrape_sites": "agent2",
    "build_brand": "agent3",
    "generate_product_images": "agent4",
    "market_pulse": "agent5",
    "check_ai_visibility": "geo",
}


def _status_text() -> str:
    with get_conn() as conn:
        by_status = conn.execute(
            "SELECT status, COUNT(*) n FROM sites GROUP BY status"
        ).fetchall()
        products = conn.execute("SELECT COUNT(*) n FROM products").fetchone()["n"]
        brands = conn.execute(
            "SELECT slug FROM generated_brand ORDER BY created_at DESC"
        ).fetchall()
    sites = ", ".join(f"{r['n']} {r['status']}" for r in by_status) or "no sites yet"
    brand_list = ", ".join(b["slug"] for b in brands) or "none"
    return f"Sites: {sites}. Products: {products}. Generated brands: {brand_list}."


def _run_tool(name: str, args: dict[str, Any]) -> str:
    if name in _ACTOR_FOR:
        set_actor(_ACTOR_FOR[name])
    try:
        if name == "discover_sites":
            rows = discover()
            return f"Discovered/updated {len(rows)} sites: " + ", ".join(
                r["name"] for r in rows[:12]
            )
        if name == "scrape_sites":
            scrape(limit=args.get("limit"))
            return _status_text()
        if name == "build_brand":
            res = build(with_images=bool(args.get("with_images")))
            b = res["brand"]
            extra = f" {res['images']} product photos." if res.get("images") else ""
            return (
                f"Built brand '{b['name']}' — {b['tagline']}. "
                f"{res['files']} files at {res['path']}.{extra}"
            )
        if name == "generate_product_images":
            from agents.agent4_images import generate_images

            r = generate_images(args.get("slug"), limit=args.get("limit"))
            return (
                f"Agent 4: {r['generated']} product photos "
                f"({r['placeholders']} placeholders) for '{r['slug']}' in {r['path']}."
            )
        if name == "market_pulse":
            from agents.agent5_market import pulse

            return f"Agent 5: {pulse()} fresh market items added to the feed."
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
