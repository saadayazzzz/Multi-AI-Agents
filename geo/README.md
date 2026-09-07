# AI Search Visibility (GEO)

Measures whether a brand shows up in AI answer engines (ChatGPT, Perplexity,
Google AI Overviews, …) for the questions its buyers actually ask — and how it
compares to competitors.

Branch: `geo-mvp`. This is the pivot away from the skincare demo. Reuses the
shared `config.py`, `db/database.py` (Postgres) and `agents/llm.py` (model layer).

## Pipeline

```
project (brand, domain, competitors, category)
   └─ generate.py   → realistic buyer queries (LLM)
        └─ probe.py  → ask each query to an answer engine (engines.py) + parse:
                       brand mentioned? position? sentiment? recommended?
                       which competitors named? brand's domain cited?
             └─ score.py → one 0-100 Visibility Score + breakdown
```

Tables (`geo/schema.sql`): `accounts`, `projects`, `queries`, `probe_runs`,
`probes`, `visibility_scores`.

## Score

`0.40·weighted_presence + 0.15·citation_rate + 0.15·reco_rate + 0.30·share_of_voice`, ×100

- **weighted_presence** — how often the brand appears, weighted by the order it's
  named (1st = 1.0, 2nd = 0.75, 3rd = 0.55, 4th = 0.4, 5th+ = 0.25)
- **citation_rate** — share of answers that link the brand's own domain
- **reco_rate** — share of answers that actively recommend the brand
- **share_of_voice** — brand mentions ÷ (brand + all competitor mentions)

## Run

```bash
python geo_cli.py initdb
python geo_cli.py new-project --account "Demo" --brand "Ahrefs" \
    --category "SEO tools" --domain ahrefs.com \
    --competitors "Semrush, Moz, SE Ranking, Ubersuggest"
python geo_cli.py gen-queries 1 -n 24
python geo_cli.py probe 1 --engine openai --samples 1 --limit 8
```

Needs Postgres up (`docker compose up -d`) and `LLM_PROVIDER=openai` + `OPENAI_API_KEY` in `.env`.

## Next

- **Engines**: Perplexity (`sonar` API), Anthropic (web search), Google AI
  Overviews (SerpAPI). Same `engines.py` signature.
- **Citations**: read structured citation annotations from the answer API instead
  of regexing URLs out of the text.
- **Sampling**: default 3 samples/query, score statistically (LLM answers vary).
- **Scheduling + alerts**: reuse the task queue / recurring jobs; e-mail / Slack
  on score drop or a competitor overtaking.
- **Recommendations**: for queries a competitor wins, fetch its cited page and
  draft the content / FAQ / schema needed to close the gap.
- **Multi-tenant + auth + Stripe usage metering** (per probe).
- Product dashboard (the JARVIS HUD stays as the marketing/demo surface).
