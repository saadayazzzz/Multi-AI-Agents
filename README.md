# JARVIS — Multi-Agent Skincare / Cosmetics System

A voice-driven console over a team of three Claude agents, plus an autonomous
worker that keeps executing tasks whether or not you're watching.

```
 Browser console (Next.js)          you talk / type here
        │  REST + WebSocket
        ▼
 FastAPI control plane  ──────────►  Postgres  ◄────────── Autonomous worker (loop)
   server/app.py                       tasks                 server/worker.py
                                    task_events             └─ JARVIS orchestrator (server/brain.py)
                                    sites / products            routes each command to:
                                    generated_brand              ├ Agent 1  discover sites
                                                                 ├ Agent 2  scrape & store
                                                                 └ Agent 3  design brand + build Next.js store
```

- **Voice** — browser Web Speech API (Chrome/Edge). Speech-to-text for commands,
  text-to-speech for JARVIS's replies. No extra keys. Falls back to a text box.
- **Brain** — `server/brain.py` is a `claude-opus-5` tool-use loop. It reads your
  natural-language command and chains the agents ("find fresh sites and rebuild the
  store" → discover → scrape → build). It can also schedule recurring tasks.
- **Autonomy** — the worker is its own process. Closing the console doesn't stop
  work; recurring tasks keep firing on their interval.

Model: `claude-opus-5` (override with `MODEL`). Storage: PostgreSQL.

## Responsible use

For **market research / reference only**. `RESPECT_ROBOTS=true` and a conservative
`SCRAPE_DELAY_SECONDS` are the defaults — keep them, and put a real contact in
`SCRAPER_USER_AGENT`. Agent 3 uses scraped data only for structure (price bands,
category mix, ingredient vocabulary); every brand name and line of copy it emits
is newly generated. Clear trademark/copyright yourself before any commercial use.

## Setup

```bash
python -m venv .venv && .venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env                # ANTHROPIC_API_KEY optional (else uses `ant` profile)
docker compose up -d                  # Postgres on :5432
python orchestrator.py initdb

cd dashboard
copy .env.local.example .env.local
npm install
cd ..
```

## Run (three terminals)

```bash
python orchestrator.py serve          # 1) FastAPI control plane  :8000
python orchestrator.py worker         # 2) autonomous task worker
cd dashboard && npm run dev           # 3) console                :3737
```

Open <http://localhost:3737>, click the mic, and speak. Example commands:

- "Discover some new skincare sites."
- "Scrape the sites we found, five at most."
- "Design a brand and build the store."
- "Find fresh sites, scrape them, then rebuild the store."
- "Keep discovering new sites every sixty minutes."   ← recurring, runs while you're away

## Headless pipeline (no console)

```bash
python orchestrator.py all            # discover -> scrape -> build
python orchestrator.py build          # just agent 3
```

## Generated stores

Agent 3 writes a runnable Next.js app per brand to `output/<slug>/`:

```bash
cd output/<slug> && npm install && npm run dev
```

## Layout

```
config.py                 env-backed settings
orchestrator.py           CLI: initdb | discover | scrape | build | all | serve | worker
db/schema.sql             sites · pages · products · brand_profiles · generated_brand · tasks · task_events
agents/
  llm.py                  Anthropic SDK wrapper (json_out / research / generate_text)
  reporter.py             pluggable progress -> task_events
  agent1_discovery.py     Claude + web_search -> scored site list
  agent2_scraper.py       polite crawl -> Claude structured extraction -> Postgres
  agent3_brand_builder.py aggregate -> original brand spec -> Next.js project
scraper/fetcher.py        robots.txt + rate limiting + HTML -> text
server/
  app.py                  FastAPI: /api/tasks, /api/stats, /api/agents, /ws
  brain.py                JARVIS orchestrator (tool-use loop over the 3 agents)
  worker.py               autonomous queue consumer
dashboard/                Next.js voice console (JARVIS UI)
output/<slug>/            generated storefronts
```
