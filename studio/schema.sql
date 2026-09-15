-- Agent 9 (Studio): AI "objects cutting" ASMR videos -> YouTube.

CREATE TABLE IF NOT EXISTS videos (
    id          SERIAL PRIMARY KEY,
    theme       TEXT NOT NULL,
    title       TEXT,
    description TEXT,
    tags        TEXT[] NOT NULL DEFAULT '{}',
    clip_count  INT,
    seconds     INT,
    path        TEXT,
    thumb_path  TEXT,
    youtube_id  TEXT,
    youtube_url TEXT,
    privacy     TEXT NOT NULL DEFAULT 'unlisted',
    status      TEXT NOT NULL DEFAULT 'draft',   -- draft | rendered | uploaded | failed
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
