-- Sales engine: a self-hosted equivalent of Gojiberry's data model
-- (confirmed via their MCP API: lists, source agents, campaign agents,
-- contacts with per-step campaignStatus, agent logs, email seats, unibox).
--
--   source agent  --imports into-->  list  <--reaches out to--  campaign agent
--
-- The list is the only link between the two agents, exactly like Gojiberry
-- (list.campaign_agent_id is where the link lives). Everything here is
-- additive / idempotent so it can be re-applied on every start.
--
-- Depends on outreach/schema.sql (campaigns, source_agents, campaign_agents).

-- ------------------------------------------------------------------ seats --
CREATE TABLE IF NOT EXISTS linkedin_seats (
    id                   SERIAL PRIMARY KEY,
    name                 TEXT NOT NULL,
    profile_url          TEXT,
    session_path         TEXT,              -- Playwright storageState file; NULL = default session.json
    sales_navigator      BOOLEAN NOT NULL DEFAULT false,
    automation_enabled   BOOLEAN NOT NULL DEFAULT false,  -- write actions (invite/message/like) opt-in
    daily_invitations    INT NOT NULL DEFAULT 20,
    daily_messages       INT NOT NULL DEFAULT 40,
    daily_visits         INT NOT NULL DEFAULT 60,
    daily_likes          INT NOT NULL DEFAULT 40,
    launch_hour          INT NOT NULL DEFAULT 9,
    active_days          INT[] NOT NULL DEFAULT '{1,2,3,4,5}',  -- ISO weekday, 1 = Monday
    timezone             TEXT NOT NULL DEFAULT 'UTC',
    created_at           TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS email_seats (
    id                       SERIAL PRIMARY KEY,
    email                    TEXT NOT NULL UNIQUE,
    name                     TEXT,
    first_name               TEXT,
    last_name                TEXT,
    type                     TEXT NOT NULL DEFAULT 'smtp',   -- smtp | google | outlook
    smtp_host                TEXT,
    smtp_port                INT NOT NULL DEFAULT 587,
    smtp_user                TEXT,
    smtp_pass                TEXT,
    imap_host                TEXT,
    imap_port                INT NOT NULL DEFAULT 993,
    daily_email_max          INT NOT NULL DEFAULT 30,
    launch_hour              INT NOT NULL DEFAULT 9,
    active_days              INT[] NOT NULL DEFAULT '{1,2,3,4,5}',
    timezone                 TEXT NOT NULL DEFAULT 'UTC',
    track_opening            BOOLEAN NOT NULL DEFAULT true,
    remove_unsubscribe_link  BOOLEAN NOT NULL DEFAULT false,
    warmup_enabled           BOOLEAN NOT NULL DEFAULT true,
    warmup_completed         BOOLEAN NOT NULL DEFAULT false,
    warmup_started_at        TIMESTAMPTZ,
    signature                TEXT,
    last_imap_uid            BIGINT,
    created_at               TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- One row per seat/day/action - the real daily caps, not an estimate.
CREATE TABLE IF NOT EXISTS seat_daily_usage (
    seat_kind  TEXT NOT NULL,      -- linkedin | email
    seat_id    INT NOT NULL,
    day        DATE NOT NULL,
    action     TEXT NOT NULL,      -- invitation | message | visit | like | email
    count      INT NOT NULL DEFAULT 0,
    PRIMARY KEY (seat_kind, seat_id, day, action)
);

-- ------------------------------------------------------- campaign agents --
-- campaign_agents is created by outreach/schema.sql; here it grows into the
-- full Gojiberry campaign object.
ALTER TABLE campaign_agents ALTER COLUMN campaign_id DROP NOT NULL;
ALTER TABLE campaign_agents ADD COLUMN IF NOT EXISTS name TEXT;
ALTER TABLE campaign_agents ADD COLUMN IF NOT EXISTS offer TEXT;
ALTER TABLE campaign_agents ADD COLUMN IF NOT EXISTS sender_name TEXT;
ALTER TABLE campaign_agents ADD COLUMN IF NOT EXISTS language TEXT;
ALTER TABLE campaign_agents ADD COLUMN IF NOT EXISTS linkedin_seat_id INT REFERENCES linkedin_seats(id) ON DELETE SET NULL;
ALTER TABLE campaign_agents ADD COLUMN IF NOT EXISTS email_seat_ids INT[] NOT NULL DEFAULT '{}';
ALTER TABLE campaign_agents ADD COLUMN IF NOT EXISTS active_days INT[];
ALTER TABLE campaign_agents ADD COLUMN IF NOT EXISTS exclude_first_degree BOOLEAN NOT NULL DEFAULT true;
ALTER TABLE campaign_agents ADD COLUMN IF NOT EXISTS split_linkedin_messages BOOLEAN NOT NULL DEFAULT false;
ALTER TABLE campaign_agents ADD COLUMN IF NOT EXISTS is_manual BOOLEAN NOT NULL DEFAULT false;
ALTER TABLE campaign_agents ADD COLUMN IF NOT EXISTS last_tick_at TIMESTAMPTZ;
ALTER TABLE campaign_agents ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT now();

-- ------------------------------------------------------------------ lists --
CREATE TABLE IF NOT EXISTS sales_lists (
    id                 SERIAL PRIMARY KEY,
    name               TEXT NOT NULL,
    campaign_agent_id  INT REFERENCES campaign_agents(id) ON DELETE SET NULL,
    custom_fields      JSONB,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at         TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- --------------------------------------------------------- source agents --
ALTER TABLE source_agents ADD COLUMN IF NOT EXISTS list_id INT REFERENCES sales_lists(id) ON DELETE SET NULL;
ALTER TABLE source_agents ADD COLUMN IF NOT EXISTS variables JSONB NOT NULL DEFAULT '[]';
    -- [{"type": "SEARCH_KEYWORD", "value": "ai agents", "enabled": true,
    --   "options": {}, "linkedin_seat_id": null, "strength": "low",
    --   "last_usage": "...", "nb_results_last_launch": 3}, ...]
ALTER TABLE source_agents ADD COLUMN IF NOT EXISTS mandatory_keywords TEXT[] NOT NULL DEFAULT '{}';
ALTER TABLE source_agents ADD COLUMN IF NOT EXISTS additional_criteria TEXT NOT NULL DEFAULT '';
ALTER TABLE source_agents ADD COLUMN IF NOT EXISTS skip_icp_filter BOOLEAN NOT NULL DEFAULT false;
ALTER TABLE source_agents ADD COLUMN IF NOT EXISTS lead_waterfall BOOLEAN NOT NULL DEFAULT true;
ALTER TABLE source_agents ADD COLUMN IF NOT EXISTS max_credit_usage INT;
ALTER TABLE source_agents ADD COLUMN IF NOT EXISTS current_credit_usage INT NOT NULL DEFAULT 0;
ALTER TABLE source_agents ADD COLUMN IF NOT EXISTS run_interval_minutes INT NOT NULL DEFAULT 240;
ALTER TABLE source_agents ADD COLUMN IF NOT EXISTS leads_per_run INT NOT NULL DEFAULT 25;
ALTER TABLE source_agents ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT now();

-- Old agents stored plain keywords; carry them over as SEARCH_KEYWORD signals once.
UPDATE source_agents SET variables = (
    SELECT COALESCE(jsonb_agg(jsonb_build_object(
        'type', 'SEARCH_KEYWORD', 'value', k->>'value', 'enabled', true,
        'last_usage', k->'last_usage', 'nb_results_last_launch', k->'nb_results_last_launch'
    )), '[]'::jsonb)
    FROM jsonb_array_elements(keywords) k
)
WHERE variables = '[]'::jsonb AND keywords <> '[]'::jsonb;

-- -------------------------------------------------------------- companies --
CREATE TABLE IF NOT EXISTS sales_companies (
    id                  SERIAL PRIMARY KEY,
    name                TEXT NOT NULL,
    domain              TEXT,
    linkedin_url        TEXT,
    website             TEXT,
    industry            TEXT,
    size                TEXT,              -- '2-10' | '11-50' | ... (Gojiberry brackets)
    company_type        TEXT,
    headquarters        TEXT,
    description         TEXT,
    is_b2b              BOOLEAN,
    is_hiring           BOOLEAN,
    technologies        TEXT[] NOT NULL DEFAULT '{}',
    last_funding_at     DATE,
    last_funding_round  TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_sales_companies_domain ON sales_companies (lower(domain)) WHERE domain IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS uq_sales_companies_li ON sales_companies (linkedin_url) WHERE linkedin_url IS NOT NULL;

-- --------------------------------------------------------------- contacts --
CREATE TABLE IF NOT EXISTS sales_contacts (
    id                  SERIAL PRIMARY KEY,
    first_name          TEXT,
    last_name           TEXT,
    full_name           TEXT,
    job_title           TEXT,
    headline            TEXT,
    profile_url         TEXT,
    location            TEXT,
    company_id          INT REFERENCES sales_companies(id) ON DELETE SET NULL,
    company             TEXT,
    company_url         TEXT,
    website             TEXT,
    industry            TEXT,
    email               TEXT,
    email_enriched      BOOLEAN NOT NULL DEFAULT false,
    email_status        TEXT NOT NULL DEFAULT 'unknown',   -- unknown | guessed | mx_valid | verified | not_found | bounced
    phone               TEXT,
    phone_enriched      BOOLEAN NOT NULL DEFAULT false,
    intent_type         TEXT,              -- the signal that found them (SEARCH_KEYWORD, RECENT_ACTIVITY, ...)
    intent              TEXT,              -- the evidence, in their words where possible
    intent_url          TEXT,
    intent_at           TIMESTAMPTZ,
    signal_value        TEXT,              -- the variable value that matched (keyword, page url, ...)
    scoring             JSONB,             -- {"persona": 0-1, "company": 0-1, "intent": 0-1, "reasons": "..."}
    total_score         NUMERIC,           -- 0-3, same range as Gojiberry's totalScoring
    agent_id            INT REFERENCES source_agents(id) ON DELETE SET NULL,
    connection_degree   INT,               -- 1 | 2 | 3, NULL = unknown
    open_to_work        BOOLEAN NOT NULL DEFAULT false,
    unsubscribed        BOOLEAN NOT NULL DEFAULT false,
    rejected            BOOLEAN NOT NULL DEFAULT false,
    rejected_reason     TEXT,
    notes               TEXT,
    custom              JSONB,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);
ALTER TABLE sales_contacts ADD COLUMN IF NOT EXISTS notion_page_id TEXT;
ALTER TABLE sales_contacts ADD COLUMN IF NOT EXISTS pitch_draft TEXT;
ALTER TABLE sales_contacts ADD COLUMN IF NOT EXISTS linkedin_note_draft TEXT;
CREATE UNIQUE INDEX IF NOT EXISTS uq_sales_contacts_profile ON sales_contacts (profile_url) WHERE profile_url IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_sales_contacts_email ON sales_contacts (lower(email));
CREATE INDEX IF NOT EXISTS idx_sales_contacts_agent ON sales_contacts (agent_id, created_at);
CREATE INDEX IF NOT EXISTS idx_sales_contacts_intent ON sales_contacts (intent_type);

CREATE TABLE IF NOT EXISTS sales_list_contacts (
    list_id     INT NOT NULL REFERENCES sales_lists(id) ON DELETE CASCADE,
    contact_id  INT NOT NULL REFERENCES sales_contacts(id) ON DELETE CASCADE,
    added_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (list_id, contact_id)
);
CREATE INDEX IF NOT EXISTS idx_sales_list_contacts_contact ON sales_list_contacts (contact_id);

-- Gojiberry's contact.campaignStatus[]: one row per contact x campaign x step.
CREATE TABLE IF NOT EXISTS sales_campaign_status (
    id                 BIGSERIAL PRIMARY KEY,
    contact_id         INT NOT NULL REFERENCES sales_contacts(id) ON DELETE CASCADE,
    campaign_agent_id  INT NOT NULL REFERENCES campaign_agents(id) ON DELETE CASCADE,
    step_id            TEXT NOT NULL,
    step_number        INT NOT NULL,
    type               TEXT NOT NULL,
    state              TEXT NOT NULL DEFAULT 'waiting',
        -- waiting | pending | manual | sent | delivered | accepted | answered | skipped | failed
    due_at             TIMESTAMPTZ,
    done_at            TIMESTAMPTZ,
    seat_id            INT,
    subject            TEXT,
    body               TEXT,
    error              TEXT,
    attempts           INT NOT NULL DEFAULT 0,
    updated_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (contact_id, campaign_agent_id, step_number)
);
CREATE INDEX IF NOT EXISTS idx_sales_cs_due ON sales_campaign_status (campaign_agent_id, state, due_at);

-- ----------------------------------------------------------- agent logs --
CREATE TABLE IF NOT EXISTS sales_agent_runs (
    id              BIGSERIAL PRIMARY KEY,
    agent_id        INT NOT NULL REFERENCES source_agents(id) ON DELETE CASCADE,
    variable_type   TEXT NOT NULL,
    variable_value  TEXT,
    status          TEXT NOT NULL DEFAULT 'running',  -- running | success | failed | skipped
    found           INT NOT NULL DEFAULT 0,           -- raw candidates the signal returned
    duplicates      INT NOT NULL DEFAULT 0,
    filtered        INT NOT NULL DEFAULT 0,           -- ignored company / mandatory keyword / open-to-work
    below_score     INT NOT NULL DEFAULT 0,
    imported        INT NOT NULL DEFAULT 0,
    error           TEXT,
    details         JSONB,
    started_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at     TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_sales_agent_runs ON sales_agent_runs (agent_id, started_at DESC);

-- ----------------------------------------------------------------- unibox --
CREATE TABLE IF NOT EXISTS sales_threads (
    id                    SERIAL PRIMARY KEY,
    channel               TEXT NOT NULL,      -- linkedin | email
    seat_id               INT,
    external_id           TEXT NOT NULL,      -- LinkedIn thread url / email root Message-ID
    contact_id            INT REFERENCES sales_contacts(id) ON DELETE SET NULL,
    attendee_full_name    TEXT,
    attendee_profile_url  TEXT,
    attendee_email        TEXT,
    subject               TEXT,
    last_message_at       TIMESTAMPTZ,
    last_message_preview  TEXT,
    seen                  BOOLEAN NOT NULL DEFAULT false,
    interested            BOOLEAN,
    created_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (channel, seat_id, external_id)
);
CREATE INDEX IF NOT EXISTS idx_sales_threads_last ON sales_threads (last_message_at DESC);

CREATE TABLE IF NOT EXISTS sales_thread_messages (
    id           BIGSERIAL PRIMARY KEY,
    thread_id    INT NOT NULL REFERENCES sales_threads(id) ON DELETE CASCADE,
    direction    TEXT NOT NULL,          -- in | out
    sender       TEXT,
    body         TEXT NOT NULL DEFAULT '',
    sent_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    external_id  TEXT,
    attachment   JSONB,
    status       TEXT NOT NULL DEFAULT 'received',   -- received | sent | queued | failed
    UNIQUE (thread_id, external_id)
);

-- ----------------------------------------------------------- email events --
CREATE TABLE IF NOT EXISTS sales_email_events (
    id                 BIGSERIAL PRIMARY KEY,
    token              TEXT NOT NULL,
    status_id          BIGINT REFERENCES sales_campaign_status(id) ON DELETE CASCADE,
    kind               TEXT NOT NULL,     -- open | unsubscribe | bounce | reply
    ts                 TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_sales_email_events_token ON sales_email_events (token);

-- -------------------------------------------------- website-visitor agent --
ALTER TABLE source_agents ADD COLUMN IF NOT EXISTS tracking_script_id TEXT;
ALTER TABLE source_agents ADD COLUMN IF NOT EXISTS script_installed BOOLEAN NOT NULL DEFAULT false;
CREATE UNIQUE INDEX IF NOT EXISTS uq_source_agents_tracking ON source_agents (tracking_script_id) WHERE tracking_script_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS sales_site_visits (
    id           BIGSERIAL PRIMARY KEY,
    agent_id     INT NOT NULL REFERENCES source_agents(id) ON DELETE CASCADE,
    ip           TEXT,
    page_url     TEXT,
    referrer     TEXT,
    user_agent   TEXT,
    org          TEXT,          -- reverse-IP organisation, when resolvable
    org_domain   TEXT,
    processed    BOOLEAN NOT NULL DEFAULT false,
    ts           TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_sales_site_visits ON sales_site_visits (agent_id, processed, ts);

-- Live LinkedIn people-search results, held until revealed into a list.
CREATE TABLE IF NOT EXISTS sales_directory_cache (
    id           SERIAL PRIMARY KEY,
    profile_url  TEXT NOT NULL UNIQUE,
    payload      JSONB NOT NULL,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);
