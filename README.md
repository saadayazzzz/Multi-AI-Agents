# JARVIS — Multi-Agent Growth & Content Console

A voice-driven, Iron-Man-style console over a team of nine specialist agents,
plus an autonomous worker that keeps executing tasks whether or not you're
watching.

```
 Browser console (Next.js, :3737)       you talk / type here
        │  REST + WebSocket
        ▼
 FastAPI control plane  ──────────►  Postgres  ◄────────── Autonomous worker (loop)
   server/app.py                       tasks                 server/worker.py
                                    task_events             └─ JARVIS orchestrator (server/brain.py)
                                    trends / content_pieces      routes each command to:
                                    market_feed / ads               ├ Agent 1  Trend Scout
                                    (+ geo/, outreach/,              ├ Agent 2  Content Studio
                                     studio/ schemas)                ├ Agent 3  Visual Studio
                                                                     ├ Agent 4  Publisher
                                                                     ├ Agent 5  AI-Search Pulse
                                                                     ├ Agent 6  AI Search Visibility (GEO)
                                                                     ├ Agent 7  Outbound Sales
                                                                     ├ Agent 8  Video Studio
                                                                     └ Agent 9  Ad Studio
```

- **Voice** — browser Web Speech API (Chrome/Edge). Speech-to-text for commands,
  text-to-speech for JARVIS's replies. No extra keys. Falls back to a text box.
- **Brain** — `server/brain.py` is a tool-use loop (Gemini/OpenAI/Anthropic,
  whichever `LLM_PROVIDER` you pick). It reads your natural-language command
  and chains agents as needed, then reports back in one spoken line.
- **Autonomy** — the worker is its own process. Closing the console doesn't
  stop work; recurring tasks (`schedule_recurring`) keep firing on interval,
  and Agent 5 pulses the AI-search news feed on its own.
- **In-console video** — click a rendered ad or ASMR video in the dashboard
  and it plays right there in a holographic viewer, no YouTube round-trip.

## The nine agents

| # | Name | Does |
|---|------|------|
| 1 | Trend Scout | researches what's trending on YouTube/Instagram/LinkedIn right now |
| 2 | Content Studio | writes a platform-native script/caption/hashtags/CTA for a topic |
| 3 | Visual Studio | generates a thumbnail/cover image for a piece of content |
| 4 | Publisher | posts finished content live (LinkedIn/Instagram/YouTube) — **only on your explicit approval** |
| 5 | AI-Search Pulse | scans AI-search/GEO industry news into a live feed |
| 6 | AI Search Visibility (GEO) | scores how visible a brand is in AI answer engines vs. competitors, 0-100 |
| 7 | Outbound Sales | prospects ICP-matched companies, runs Agent 6 on each, drafts cold-email sequences, exports `leads.xlsx` |
| 8 | Video Studio | AI "objects cutting" ASMR videos → assemble → thumbnail → optional YouTube upload |
| 9 | Ad Studio | faceless AI UGC ad creatives (script + voiceover + B-roll + burned captions) → optional YouTube Shorts upload |

Everything that posts or uploads publicly defaults to safe/reversible
(UNLISTED YouTube uploads with an AI-content disclosure, no LinkedIn/
Instagram post without your explicit go-ahead in the conversation).

## Model backend

Provider-agnostic (`agents/llm.py`) — pick with `LLM_PROVIDER`:

- `gemini` (**default, recommended**) — free tier, no card. `GEMINI_API_KEY`
  from [aistudio.google.com/apikey](https://aistudio.google.com/apikey).
- `openai` — needs a billed `OPENAI_API_KEY`.
- `anthropic` — a real API key or a `claude setup-token` OAuth token.

**Images** go through their own chain regardless of `LLM_PROVIDER`, first
match wins: **OpenRouter** (`OPENROUTER_API_KEY`, cheap + good quality,
[openrouter.ai](https://openrouter.ai/settings/keys)) → **OpenAI**
(`gpt-image-1`) → the active backend's own image model (Gemini's is
free-tier-gated to 0 quota) → **Pollinations.ai** (free, no key, last resort).

**Video** (Agent 8/9 B-roll clips) — `VIDEO_PROVIDER`: `comfy` (local
ComfyUI on your own GPU, free & unlimited — see `studio/README_comfy.md`),
`hf` (Hugging Face Inference, small free credit), or `openai` (Sora, paid).
Agent 9's voiceover is always free (`edge-tts`, no key).

## Setup

```bash
python -m venv .venv && .venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env                # fill in at least GEMINI_API_KEY
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

- "What's trending on LinkedIn right now?"
- "Write a LinkedIn post about AI agents and make a thumbnail."
- "How visible is Notion in AI search compared to Coda and ClickUp?"
- "Find me clients — ICP is Series A SaaS founders, offer is AI agent builds."
- "Make a soap-cutting ASMR video and upload it."
- "Make a UGC ad for natural hair growth remedies, 20 seconds."
- "Keep finding trends every sixty minutes." ← recurring, runs while you're away

## Headless pipeline (no console)

```bash
python orchestrator.py all            # trends -> content -> visuals -> publish
python orchestrator.py trends --platform linkedin
python orchestrator.py content --platform linkedin
python orchestrator.py visuals --content-id 12
python orchestrator.py publish --content-id 12

python studio_cli.py auth                              # one-time YouTube OAuth
python studio_cli.py make "soap cutting" --upload
python ads_cli.py make "skincare" --product "vitamin C serum" --upload
python geo_cli.py new-project --account jarvis --brand acme --category "SEO tools" --competitors ahrefs,semrush
python outreach_cli.py campaign --name jarvis --icp "..." --offer "..."
```

## Sales engine (self-hosted Gojiberry)

`sales/` is a self-hosted version of Gojiberry's data model and workflow,
built from what their own MCP API shows: **source agents** find and score
leads into **lists**, **campaign agents** run LinkedIn + email sequences
against those lists, and every reply lands in the **unibox**.

```bash
python -m sales.server       # console + API on :8092 (also served by the main server at /sales)
python -m sales.scheduler    # keeps agents sourcing and campaigns sending on their own
cd outreach/linkedin_scraper && npm install   # once: playwright-core for LinkedIn seats
```

Open <http://localhost:8092/sales/>. Then:

1. **Settings**: add a LinkedIn seat and click *Log in*. A real Chrome window
   opens; sign in by hand, and only the session cookies are kept. Add a
   Gmail/Outlook mailbox with an app password.
2. **Agents → New agent**: build the ICP from your website, pick 4-15
   signals and write your offer. This creates a list, a source agent and an
   inactive campaign together (Gojiberry's "Full Cycle").
3. Activate the campaign once you've checked the sequence. The scheduler
   sends on the campaign's active days, from its launch hour, within each
   seat's daily caps.

| Gojiberry | Here |
|---|---|
| Source agent (ICP, `minLeadScore`, `leadWaterfall`, ignored companies, mandatory keywords, service-provider and open-to-work filters, pause) | `sales/agents.py`, `sales/runner.py` |
| 17 signal types (`SEARCH_KEYWORD*`, `EVENT_KEYWORD`, `GROUP_KEYWORD`, competitor/influencer/company pages, profile visitors, followers, `RECENT_ACTIVITY`, `RECENTLY_CHANGED_JOB`, `RECENT_FUNDING_EVENT`, `HIRING`, `TECHNOLOGY`) | `sales/signals.py`. LinkedIn signals read through your seat; funding, hiring and technology come from live web search |
| Lookalike and website-visitor agents | `sales/runner.py`, `sales/tracking.py` (tracking snippet plus reverse-IP company match) |
| Lead score 0-3 | `sales/scoring.py`: persona + company (LLM) + intent (signal strength × freshness) |
| Agent logs | `sales_agent_runs`, one row per signal run with found / duplicates / filtered / below-score / imported |
| Lists, contacts, CSV import, reject/unreject | `sales/lists.py` |
| Campaign agent: 7 step types, step-order rules, delays, AI or template messages with `[FirstName]` `[LastName]` `[Company]`, `skipInvitationAfterDays`, exclude 1st-degree, split messages, launch hour, active days | `sales/campaigns.py`, `sales/executor.py`, `sales/writer.py` |
| Email seats, warm-up, open tracking, unsubscribe | `sales/emailer.py` (SMTP/IMAP, volume ramp, pixel, one-click unsubscribe, bounce handling) |
| Email and phone enrichment | `sales/enrich.py`: Hunter or Apollo if configured, otherwise a pattern guess on a domain with valid MX |
| Lead and company directory (search masked, reveal into a list) | `sales/directory.py`: your own workspace, or a live LinkedIn people search |
| Unibox (threads, interested/seen, reply) | `sales/unibox.py`. A reply stops that contact's remaining steps |
| Reply rate | `campaign_stats()`, using Gojiberry's own definition |

**LinkedIn automation is opt-in, per seat.** Automated invitations, messages,
likes and profile visits break LinkedIn's terms, and accounts get
restricted. On a seat without automation, every LinkedIn step becomes a
**task** with the drafted text, and you do it yourself in one click
(Gojiberry's manual campaigns work the same way). Reading through a seat for
signals, acceptances and the inbox is always on.

Not included: Gojiberry's shared pool of pre-indexed leads (the directory
searches your own workspace or LinkedIn live), a real warm-up network (you
get a volume ramp instead), credits, and multi-user organisations.

Tests: `pip install pytest && pytest tests/` (needs a local Postgres; set
`TEST_DATABASE_URL` if it isn't on `127.0.0.1:5432`).

## Layout

```
config.py                 env-backed settings (LLM/image/video providers, DB, server)
orchestrator.py           CLI: initdb | trends | content | visuals | publish | all | serve | worker
db/schema.sql             trends · content_pieces · content_images · tasks · task_events ·
                           system_state · market_feed · ads
agents/
  llm.py                  provider-agnostic model layer (Gemini/OpenAI/Anthropic) +
                           the OpenRouter -> OpenAI -> native -> Pollinations image chain
  reporter.py              pluggable progress -> task_events
  agent1_trends.py         Agent 1 — trend research
  agent2_content.py        Agent 2 — platform-native copywriting
  agent3_visuals.py        Agent 3 — thumbnail/cover generation
  agent4_publisher.py      Agent 4 — LinkedIn/Instagram/YouTube posting
  agent5_market.py         Agent 5 — AI-search/GEO news feed
  platforms/               per-platform posting clients
scraper/fetcher.py        polite crawl utility (robots.txt + rate limiting)
geo/                      Agent 6 — AI Search Visibility pipeline (own schema.sql)
outreach/                 Agent 7 — outbound sales/prospecting pipeline (own schema.sql)
studio/                   Agent 8 — Video Studio: script -> clips -> ffmpeg assemble ->
                           thumbnail -> YouTube (own schema.sql; see README_comfy.md)
ads/                      Agent 9 — Ad Studio: script -> edge-tts voiceover -> B-roll ->
                           ffmpeg assemble + burned captions -> YouTube
server/
  app.py                  FastAPI: /api/tasks, /api/stats, /api/agents, /api/geo,
                           /api/outreach, /api/studio, /api/ads, /media, /ws
  brain.py                JARVIS orchestrator (tool-use loop over all nine agents)
  worker.py               autonomous queue consumer + Agent 5 pulse timer
dashboard/                Next.js voice console (JARVIS HUD, in-console video viewer)
output/                   generated content images, videos, and ad renders
```

## Other branches

- `cyber_jarvis` — Agent 8 there is an authorized, non-destructive domain
  security assessment (subdomains, TLS, headers, exposed files, CVE
  correlation). Only ever run against domains you own or are explicitly
  authorized to test.

## Responsible use

Publishing to LinkedIn/Instagram/YouTube always requires your explicit
approval in the conversation — nothing posts or uploads on its own. YouTube
uploads default to **unlisted** with an AI-generated-content disclosure in
the description; review before making anything public. Outreach emails are
gated behind SMTP configuration and honour a suppression list. In the sales
engine, LinkedIn write actions (invitations, DMs, likes) only run on a seat
where you've turned automation on, within daily caps. Without it, they
become manual tasks, because automating LinkedIn breaks its terms and risks
a ban. Cyber assessments (on `cyber_jarvis`) run only against
explicitly authorized targets.
