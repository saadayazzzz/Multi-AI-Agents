-- Schema for the autonomous viral-content marketing pipeline.

DROP TABLE IF EXISTS sites, pages, products, brand_profiles, generated_brand, generated_images, market_feed CASCADE;

-- Agent 1 (Trend Scout): trending topics/formats, scoped per platform.
CREATE TABLE IF NOT EXISTS trends (
    id            SERIAL PRIMARY KEY,
    platform      TEXT NOT NULL,             -- youtube | instagram | linkedin
    topic         TEXT NOT NULL,
    angle         TEXT,                      -- suggested content angle/hook
    format        TEXT,                      -- short-form video | carousel | text-post | ...
    rationale     TEXT,
    score         NUMERIC,                   -- 0-10 "how hot right now"
    source        TEXT,
    status        TEXT NOT NULL DEFAULT 'new',  -- new | used | stale
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (platform, topic)
);
CREATE INDEX IF NOT EXISTS idx_trends_platform ON trends (platform, status, score DESC);

-- Agent 2 (Content Studio): one piece of content per platform per trend/topic.
CREATE TABLE IF NOT EXISTS content_pieces (
    id            SERIAL PRIMARY KEY,
    trend_id      INT REFERENCES trends(id) ON DELETE SET NULL,
    platform      TEXT NOT NULL,
    title         TEXT,
    script        TEXT,                      -- youtube voiceover/outline or long-form body
    caption       TEXT,                      -- ig/linkedin caption text
    hashtags      TEXT[],
    cta           TEXT,
    extra         JSONB,                     -- yt tags/description, thumbnail_prompt, video_path, etc.
    status        TEXT NOT NULL DEFAULT 'draft',
        -- draft | ready | ready_manual_upload | posted | failed
    error         TEXT,
    external_post_id TEXT,                   -- id/URN returned by the platform after posting
    external_url  TEXT,
    posted_at     TIMESTAMPTZ,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_content_status ON content_pieces (platform, status, created_at DESC);

-- Agent 3 (Visual Studio): one thumbnail/cover image per content piece.
CREATE TABLE IF NOT EXISTS content_images (
    id            SERIAL PRIMARY KEY,
    content_id    INT NOT NULL REFERENCES content_pieces(id) ON DELETE CASCADE UNIQUE,
    prompt        TEXT,
    rel_path      TEXT,                      -- served path, e.g. /img/content/42.png
    kind          TEXT NOT NULL DEFAULT 'photo', -- photo | placeholder
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
    actor     TEXT NOT NULL DEFAULT 'system',  -- orchestrator | agent1 | agent2 | agent3 | agent4 | system | user
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

-- Agent 9 (Ad Studio): faceless AI UGC ad creatives - AI script + AI
-- voiceover + B-roll + burned captions, ready to post as a paid-social ad.
CREATE TABLE IF NOT EXISTS ads (
    id            SERIAL PRIMARY KEY,
    niche         TEXT NOT NULL,
    product       TEXT,
    hook          TEXT,
    script        TEXT,                          -- full voiceover text
    seconds       NUMERIC,
    path          TEXT,                          -- rendered vertical mp4
    thumb_path    TEXT,
    youtube_id    TEXT,
    youtube_url   TEXT,
    privacy       TEXT NOT NULL DEFAULT 'unlisted',
    status        TEXT NOT NULL DEFAULT 'queued', -- queued|scripted|rendered|uploaded|failed
    error         TEXT,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_ads_status ON ads (status, created_at DESC);
