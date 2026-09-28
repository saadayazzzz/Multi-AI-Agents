-- Outbound sales engine: prospect -> enrich -> visibility-score -> draft -> send -> track.

CREATE TABLE IF NOT EXISTS campaigns (
    id          SERIAL PRIMARY KEY,
    name        TEXT NOT NULL,
    icp         TEXT NOT NULL,   -- who to target (natural language)
    offer       TEXT NOT NULL,   -- the pitch, one paragraph
    from_name   TEXT,
    from_email  TEXT,
    daily_cap   INT NOT NULL DEFAULT 20,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS leads (
    id              SERIAL PRIMARY KEY,
    campaign_id     INT REFERENCES campaigns(id) ON DELETE CASCADE,
    company         TEXT NOT NULL,
    domain          TEXT,
    contact_name    TEXT,
    contact_role    TEXT,
    contact_email   TEXT,
    email_status    TEXT NOT NULL DEFAULT 'unknown',  -- unknown | guessed | verified | bounced
    linkedin_url    TEXT,
    linkedin_urn    TEXT,
    linkedin_activity TEXT,  -- when they were active, as the search result showed it
                             -- e.g. '3 days ago', 'Jan 14' - null if no date was visible
    notion_page_id  TEXT,
    industry        TEXT,
    icp_fit         INT,                              -- 0-100
    trigger         TEXT,                             -- why-now hook
    geo_project_id  INT,
    geo_score       NUMERIC,
    geo_finding     TEXT,
    status          TEXT NOT NULL DEFAULT 'new',
        -- new | enriched | scored | drafted | sent | replied
        -- | positive | negative | unsub | bounced | won | lost
    last_action_at  TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (campaign_id, domain)
);
CREATE INDEX IF NOT EXISTS idx_leads_status ON leads (campaign_id, status);
-- Additive migration for tables created before these columns existed.
ALTER TABLE leads ADD COLUMN IF NOT EXISTS linkedin_url TEXT;
ALTER TABLE leads ADD COLUMN IF NOT EXISTS linkedin_urn TEXT;
ALTER TABLE leads ADD COLUMN IF NOT EXISTS linkedin_activity TEXT;
ALTER TABLE leads ADD COLUMN IF NOT EXISTS notion_page_id TEXT;

CREATE TABLE IF NOT EXISTS messages (
    id         BIGSERIAL PRIMARY KEY,
    lead_id    INT REFERENCES leads(id) ON DELETE CASCADE,
    channel    TEXT NOT NULL DEFAULT 'email',   -- email | linkedin
    direction  TEXT NOT NULL,                   -- out | in
    step       INT,                             -- 1 = first touch, 2/3 = follow-ups
    subject    TEXT,
    body       TEXT NOT NULL,
    status     TEXT NOT NULL DEFAULT 'draft',   -- draft | queued | sent | failed | received
    ts         TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_messages_lead ON messages (lead_id, id);

CREATE TABLE IF NOT EXISTS suppression (
    email  TEXT PRIMARY KEY,
    reason TEXT,
    ts     TIMESTAMPTZ NOT NULL DEFAULT now()
);
