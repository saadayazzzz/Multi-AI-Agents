-- AI Search Visibility (GEO) — core schema.

CREATE TABLE IF NOT EXISTS accounts (
    id          SERIAL PRIMARY KEY,
    name        TEXT NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS projects (
    id           SERIAL PRIMARY KEY,
    account_id   INT REFERENCES accounts(id) ON DELETE CASCADE,
    brand        TEXT NOT NULL,
    domain       TEXT,
    competitors  TEXT[] NOT NULL DEFAULT '{}',
    topics       TEXT[] NOT NULL DEFAULT '{}',
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS queries (
    id          SERIAL PRIMARY KEY,
    project_id  INT REFERENCES projects(id) ON DELETE CASCADE,
    text        TEXT NOT NULL,
    intent      TEXT,          -- informational | commercial | comparison | alternatives | brand | local
    source      TEXT NOT NULL DEFAULT 'generated',  -- generated | user
    active      BOOLEAN NOT NULL DEFAULT true,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (project_id, text)
);

CREATE TABLE IF NOT EXISTS probe_runs (
    id           SERIAL PRIMARY KEY,
    project_id   INT REFERENCES projects(id) ON DELETE CASCADE,
    engine       TEXT NOT NULL,
    status       TEXT NOT NULL DEFAULT 'running',  -- running | done | failed
    started_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at  TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS probes (
    id                   BIGSERIAL PRIMARY KEY,
    run_id               INT REFERENCES probe_runs(id) ON DELETE CASCADE,
    query_id             INT REFERENCES queries(id) ON DELETE CASCADE,
    engine               TEXT NOT NULL,
    sample               INT NOT NULL DEFAULT 1,
    ts                   TIMESTAMPTZ NOT NULL DEFAULT now(),
    answer               TEXT,
    brand_mentioned      BOOLEAN,
    brand_position       INT,        -- 1 = brand named first among all brands; NULL = not mentioned
    sentiment            TEXT,       -- positive | neutral | negative | NULL
    brand_recommended    BOOLEAN,    -- answer positively endorses the brand (not just lists it)
    brand_cited          BOOLEAN,    -- brand's own domain appears among cited URLs
    cited_urls           TEXT[] NOT NULL DEFAULT '{}',
    competitor_mentions  TEXT[] NOT NULL DEFAULT '{}',
    raw                  JSONB
);
CREATE INDEX IF NOT EXISTS idx_probes_run ON probes (run_id);

CREATE TABLE IF NOT EXISTS visibility_scores (
    id              BIGSERIAL PRIMARY KEY,
    project_id      INT REFERENCES projects(id) ON DELETE CASCADE,
    run_id          INT REFERENCES probe_runs(id) ON DELETE CASCADE,
    engine          TEXT NOT NULL,
    computed_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    presence_rate   NUMERIC,   -- share of queries the brand appears in
    avg_position    NUMERIC,   -- mean brand_position when present
    citation_rate   NUMERIC,   -- share of queries where the brand's domain was cited
    reco_rate       NUMERIC,   -- share of queries where the brand was recommended
    share_of_voice  NUMERIC,   -- brand mentions / (brand + competitor mentions)
    score           NUMERIC,   -- 0-100 composite
    detail          JSONB
);
CREATE INDEX IF NOT EXISTS idx_scores_project ON visibility_scores (project_id, id);
