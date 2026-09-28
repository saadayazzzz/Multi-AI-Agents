-- Schema for the sales/outreach control plane.

-- One-time cleanup of tables from a since-removed earlier project. Does NOT
-- include market_feed - that's live Agent 5 data and must survive restarts.
DROP TABLE IF EXISTS sites, pages, products, brand_profiles, generated_brand, generated_images CASCADE;

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
    actor     TEXT NOT NULL DEFAULT 'system',  -- orchestrator | agent5 | geo | sales | system | user
    kind      TEXT NOT NULL DEFAULT 'log',     -- log|tool_call|tool_result|status|error|message|spoken
    message   TEXT,
    data      JSONB
);
CREATE INDEX IF NOT EXISTS idx_task_events_stream ON task_events (id);
CREATE INDEX IF NOT EXISTS idx_task_events_task ON task_events (task_id, id);

-- Single-row power switch for the whole system (toggled from the console).
CREATE TABLE IF NOT EXISTS system_state (
    id         INT PRIMARY KEY DEFAULT 1,
    power      TEXT NOT NULL DEFAULT 'on',   -- on | off
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT system_state_singleton CHECK (id = 1)
);
INSERT INTO system_state (id) VALUES (1) ON CONFLICT DO NOTHING;

-- One connected identity per external platform (LinkedIn, etc.) - the result of the
-- in-app OAuth "Connect" flow, so agents can post / personalize as the real operator
-- instead of a manually pasted long-lived token.
CREATE TABLE IF NOT EXISTS oauth_connections (
    provider      TEXT PRIMARY KEY,   -- 'linkedin'
    access_token  TEXT NOT NULL,
    author_urn    TEXT,               -- e.g. urn:li:person:xxxx (LinkedIn Posts API "author")
    profile_name  TEXT,
    profile_email TEXT,
    scope         TEXT,
    expires_at    TIMESTAMPTZ,
    connected_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Agent 5: rolling feed of AI-search / GEO industry developments.
CREATE TABLE IF NOT EXISTS market_feed (
    id         BIGSERIAL PRIMARY KEY,
    ts         TIMESTAMPTZ NOT NULL DEFAULT now(),
    headline   TEXT NOT NULL,
    detail     TEXT,
    tag        TEXT,        -- platform | shift | tool | funding | study | regulation | tactic
    sentiment  TEXT,        -- positive | neutral | negative
    region     TEXT,
    source     TEXT,
    UNIQUE (headline)
);
CREATE INDEX IF NOT EXISTS idx_market_feed_id ON market_feed (id);
