-- Schema for the multi-agent skincare/cosmetics pipeline.

CREATE TABLE IF NOT EXISTS sites (
    id            SERIAL PRIMARY KEY,
    name          TEXT NOT NULL,
    url           TEXT NOT NULL UNIQUE,
    category      TEXT,
    price_tier    TEXT,                       -- budget | mid | premium | luxury
    rationale     TEXT,
    score         NUMERIC,                    -- agent 1's 0-10 quality score
    status        TEXT NOT NULL DEFAULT 'discovered',  -- discovered|scraping|scraped|failed
    error         TEXT,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS pages (
    id            SERIAL PRIMARY KEY,
    site_id       INT NOT NULL REFERENCES sites(id) ON DELETE CASCADE,
    url           TEXT NOT NULL,
    kind          TEXT,                       -- home | collection | product | other
    http_status   INT,
    raw_text      TEXT,
    fetched_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (site_id, url)
);

CREATE TABLE IF NOT EXISTS products (
    id            SERIAL PRIMARY KEY,
    site_id       INT NOT NULL REFERENCES sites(id) ON DELETE CASCADE,
    source_url    TEXT,
    name          TEXT NOT NULL,
    brand         TEXT,
    category      TEXT,                       -- cleanser | serum | moisturizer | mask | spf | makeup | ...
    subcategory   TEXT,
    description   TEXT,
    price         NUMERIC,
    currency      TEXT,
    size          TEXT,
    ingredients   TEXT[],
    benefits      TEXT[],
    skin_types    TEXT[],
    image_url     TEXT,
    rating        NUMERIC,
    raw           JSONB,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (site_id, name, size)
);

CREATE TABLE IF NOT EXISTS brand_profiles (
    id              SERIAL PRIMARY KEY,
    site_id         INT NOT NULL REFERENCES sites(id) ON DELETE CASCADE UNIQUE,
    palette         JSONB,                    -- ["#rrggbb", ...]
    typography      JSONB,                    -- {"headings": "...", "body": "..."}
    tone            TEXT,
    tagline_samples TEXT[],
    positioning     TEXT,
    price_tier      TEXT,
    raw             JSONB
);

-- The output of agent 3: an ORIGINAL brand, not a copy of any scraped site.
CREATE TABLE IF NOT EXISTS generated_brand (
    id            SERIAL PRIMARY KEY,
    slug          TEXT NOT NULL UNIQUE,
    spec          JSONB NOT NULL,
    catalog       JSONB,
    output_path   TEXT,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- --------------------------------------------------------------------------- --
-- Control plane: the JARVIS console talks to the worker through these tables.
-- --------------------------------------------------------------------------- --

CREATE TABLE IF NOT EXISTS tasks (
    id              SERIAL PRIMARY KEY,
    prompt          TEXT NOT NULL,
    source          TEXT NOT NULL DEFAULT 'voice',   -- voice | text | schedule
    status          TEXT NOT NULL DEFAULT 'queued',  -- queued|running|done|failed|cancelled
    priority        INT  NOT NULL DEFAULT 100,       -- lower runs first
    run_after       TIMESTAMPTZ NOT NULL DEFAULT now(),
    recur_seconds   INT,                             -- if set, re-enqueue after finishing
    result_summary  TEXT,
    spoken_response TEXT,
    error           TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    started_at      TIMESTAMPTZ,
    finished_at     TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_tasks_queue ON tasks (status, priority, run_after, id);

CREATE TABLE IF NOT EXISTS task_events (
    id        BIGSERIAL PRIMARY KEY,
    task_id   INT REFERENCES tasks(id) ON DELETE CASCADE,
    ts        TIMESTAMPTZ NOT NULL DEFAULT now(),
    actor     TEXT NOT NULL DEFAULT 'system',  -- orchestrator | agent1 | agent2 | agent3 | system | user
    kind      TEXT NOT NULL DEFAULT 'log',     -- log|tool_call|tool_result|status|error|message|spoken
    message   TEXT,
    data      JSONB
);
CREATE INDEX IF NOT EXISTS idx_task_events_stream ON task_events (id);
CREATE INDEX IF NOT EXISTS idx_task_events_task ON task_events (task_id, id);

-- Agent 4: one generated product image per (brand, product).
CREATE TABLE IF NOT EXISTS generated_images (
    id            SERIAL PRIMARY KEY,
    brand_slug    TEXT NOT NULL,
    product_slug  TEXT NOT NULL,
    prompt        TEXT,
    rel_path      TEXT,                          -- served path, e.g. /img/products/foo.png
    kind          TEXT NOT NULL DEFAULT 'photo', -- photo | placeholder
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (brand_slug, product_slug)
);
