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

-- Mirrors Gojiberry's real data model (confirmed via their own MCP API, not
-- guessed from screenshots): a Source Agent finds/scores leads against an
-- ICP; a Campaign Agent runs the multi-step outreach sequence against
-- whoever a source agent found. The two are separate concerns linked by
-- source_agents.campaign_id, same as Gojiberry links them by list.
CREATE TABLE IF NOT EXISTS source_agents (
    id                      SERIAL PRIMARY KEY,
    name                    TEXT NOT NULL,
    target_job_titles       TEXT[] NOT NULL DEFAULT '{}',
    target_industries       TEXT[] NOT NULL DEFAULT '{}',
    target_company_sizes    TEXT[] NOT NULL DEFAULT '{}',
    target_locations        TEXT[] NOT NULL DEFAULT '{}',
    target_company_types    TEXT[] NOT NULL DEFAULT '{}',
    keywords                JSONB NOT NULL DEFAULT '[]',
        -- [{"value": "ai agents", "last_usage": "...", "nb_results_last_launch": 3}, ...]
    ignored_companies       TEXT[] NOT NULL DEFAULT '{}',
    min_lead_score          NUMERIC NOT NULL DEFAULT 0.5,  -- 0-1, same scale as icp_fit/100
    exclude_service_providers      BOOLEAN NOT NULL DEFAULT true,
    include_open_to_work_profiles  BOOLEAN NOT NULL DEFAULT false,
    agent_type              TEXT NOT NULL DEFAULT 'autopilot',
    paused                  BOOLEAN NOT NULL DEFAULT false,
    last_run                TIMESTAMPTZ,
    campaign_id             INT REFERENCES campaigns(id) ON DELETE SET NULL,
    created_at               TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS campaign_agents (
    id                          SERIAL PRIMARY KEY,
    campaign_id                 INT NOT NULL REFERENCES campaigns(id) ON DELETE CASCADE,
    steps                       JSONB NOT NULL DEFAULT '[]',
        -- [{"type": "invitation"|"message"|"email"|"visitProfile", "step_number": 0,
        --   "message_mode": "ai"|"manual", "message": "", "subject": "",
        --   "like_posts_before_invitation": true, "delay_after_last_step": 2}, ...]
        -- messages here are DRAFTS for the user to review/send manually - see
        -- prospect.py's docstring for why there's no automated LinkedIn send.
    tone                         TEXT NOT NULL DEFAULT 'professional',
    goal                         TEXT NOT NULL DEFAULT 'warm',  -- warm | demos
    launch_hour                  INT NOT NULL DEFAULT 9,
    skip_invitation_after_days   INT NOT NULL DEFAULT 7,
    active                       BOOLEAN NOT NULL DEFAULT false,
    created_at                   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS suppression (
    email  TEXT PRIMARY KEY,
    reason TEXT,
    ts     TIMESTAMPTZ NOT NULL DEFAULT now()
);
