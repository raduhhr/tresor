CREATE TABLE IF NOT EXISTS schema_migrations (
    version text PRIMARY KEY,
    applied_at timestamptz NOT NULL DEFAULT now()
);

CREATE EXTENSION IF NOT EXISTS pg_trgm;

CREATE TABLE IF NOT EXISTS sources (
    id text PRIMARY KEY,
    name text NOT NULL,
    source_type text NOT NULL,
    category text NOT NULL,
    url text NOT NULL,
    enabled boolean NOT NULL DEFAULT true,
    interval_minutes integer NOT NULL DEFAULT 60 CHECK (interval_minutes > 0),
    parser text NOT NULL DEFAULT 'rss_article',
    config jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS fetch_runs (
    id bigserial PRIMARY KEY,
    source_id text REFERENCES sources(id) ON DELETE SET NULL,
    started_at timestamptz NOT NULL DEFAULT now(),
    finished_at timestamptz,
    status text NOT NULL DEFAULT 'running',
    http_status integer,
    items_found integer NOT NULL DEFAULT 0,
    items_new integer NOT NULL DEFAULT 0,
    items_changed integer NOT NULL DEFAULT 0,
    error text,
    bytes_downloaded bigint NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS items (
    id bigserial PRIMARY KEY,
    source_id text NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
    item_type text NOT NULL,
    canonical_url text NOT NULL,
    external_id text,
    title text NOT NULL,
    description text,
    first_seen_at timestamptz NOT NULL DEFAULT now(),
    last_seen_at timestamptz NOT NULL DEFAULT now(),
    published_at timestamptz,
    latest_hash text NOT NULL,
    current_status text NOT NULL DEFAULT 'active',
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    UNIQUE (source_id, canonical_url)
);

CREATE INDEX IF NOT EXISTS idx_items_type_seen ON items (item_type, first_seen_at DESC);
CREATE INDEX IF NOT EXISTS idx_items_source_seen ON items (source_id, first_seen_at DESC);
CREATE INDEX IF NOT EXISTS idx_items_metadata_gin ON items USING gin (metadata);

CREATE TABLE IF NOT EXISTS item_versions (
    id bigserial PRIMARY KEY,
    item_id bigint NOT NULL REFERENCES items(id) ON DELETE CASCADE,
    observed_at timestamptz NOT NULL DEFAULT now(),
    title text NOT NULL,
    description text,
    content_text text,
    content_hash text NOT NULL,
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    UNIQUE (item_id, content_hash)
);

CREATE INDEX IF NOT EXISTS idx_item_versions_observed ON item_versions (observed_at DESC);

CREATE TABLE IF NOT EXISTS observations (
    id bigserial PRIMARY KEY,
    item_id bigint NOT NULL REFERENCES items(id) ON DELETE CASCADE,
    observed_at timestamptz NOT NULL DEFAULT now(),
    observation_type text NOT NULL,
    value_num numeric,
    value_text text,
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS idx_observations_type_time ON observations (observation_type, observed_at DESC);
CREATE INDEX IF NOT EXISTS idx_observations_item_type_time ON observations (item_id, observation_type, observed_at DESC);

CREATE TABLE IF NOT EXISTS quarantine_items (
    id bigserial PRIMARY KEY,
    source_id text REFERENCES sources(id) ON DELETE SET NULL,
    fetch_run_id bigint REFERENCES fetch_runs(id) ON DELETE SET NULL,
    seen_at timestamptz NOT NULL DEFAULT now(),
    reason text NOT NULL,
    payload jsonb NOT NULL DEFAULT '{}'::jsonb
);

CREATE TABLE IF NOT EXISTS alert_rules (
    id text PRIMARY KEY,
    name text NOT NULL,
    enabled boolean NOT NULL DEFAULT true,
    mode text NOT NULL DEFAULT 'digest',
    match jsonb NOT NULL DEFAULT '{}'::jsonb,
    channel text NOT NULL DEFAULT 'discord',
    config jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS alert_events (
    id bigserial PRIMARY KEY,
    rule_id text REFERENCES alert_rules(id) ON DELETE SET NULL,
    item_id bigint REFERENCES items(id) ON DELETE SET NULL,
    channel text NOT NULL,
    dedupe_key text NOT NULL,
    payload jsonb NOT NULL DEFAULT '{}'::jsonb,
    sent_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (rule_id, dedupe_key)
);

CREATE TABLE IF NOT EXISTS api_cache (
    key text PRIMARY KEY,
    payload jsonb NOT NULL,
    refreshed_at timestamptz NOT NULL DEFAULT now(),
    expires_at timestamptz,
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS idx_api_cache_expires ON api_cache (expires_at);

CREATE TABLE IF NOT EXISTS parliament_votes (
    vote_id text PRIMARY KEY,
    item_id bigint NOT NULL UNIQUE REFERENCES items(id) ON DELETE CASCADE,
    chamber text NOT NULL,
    source_id text NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
    vote_time timestamptz NOT NULL,
    title text NOT NULL,
    vote_kind text,
    outcome text,
    bill_code text,
    bill_number integer,
    bill_year integer,
    bill_key text,
    bill_url text,
    nominal_url text NOT NULL,
    present_count integer,
    yes_count integer,
    no_count integer,
    abstain_count integer,
    not_voted_count integer,
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

ALTER TABLE parliament_votes
ADD COLUMN IF NOT EXISTS bill_key text;

CREATE INDEX IF NOT EXISTS idx_parliament_votes_time ON parliament_votes (vote_time DESC);
CREATE INDEX IF NOT EXISTS idx_parliament_votes_bill ON parliament_votes (bill_code, bill_year);
CREATE INDEX IF NOT EXISTS idx_parliament_votes_bill_code_year_number ON parliament_votes (bill_code, bill_year, bill_number);
CREATE INDEX IF NOT EXISTS idx_parliament_votes_bill_key ON parliament_votes (bill_key);
CREATE INDEX IF NOT EXISTS idx_parliament_votes_bill_key_chamber ON parliament_votes (bill_key, chamber);
CREATE INDEX IF NOT EXISTS idx_parliament_votes_outcome ON parliament_votes (outcome);
CREATE INDEX IF NOT EXISTS idx_parliament_votes_chamber_time ON parliament_votes (chamber, vote_time DESC);
CREATE INDEX IF NOT EXISTS idx_parliament_votes_title_trgm ON parliament_votes USING gin (title gin_trgm_ops);

CREATE TABLE IF NOT EXISTS parliament_bills (
    bill_key text PRIMARY KEY,
    source_id text REFERENCES sources(id) ON DELETE SET NULL,
    source_site text,
    bill_code text NOT NULL,
    bill_number integer NOT NULL,
    bill_year integer NOT NULL,
    label text,
    title text,
    short_title text,
    description text,
    procedure text,
    decisional_chamber text,
    initiative_type text,
    urgency boolean,
    urgency_text text,
    stage text,
    initiators text[] NOT NULL DEFAULT '{}'::text[],
    registration_numbers jsonb NOT NULL DEFAULT '{}'::jsonb,
    documents jsonb NOT NULL DEFAULT '[]'::jsonb,
    source_url text,
    first_seen_at timestamptz NOT NULL DEFAULT now(),
    last_seen_at timestamptz NOT NULL DEFAULT now(),
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_parliament_bills_code ON parliament_bills (bill_code, bill_year, bill_number);
CREATE INDEX IF NOT EXISTS idx_parliament_bills_year ON parliament_bills (bill_year DESC);
CREATE INDEX IF NOT EXISTS idx_parliament_bills_stage ON parliament_bills (stage);
CREATE INDEX IF NOT EXISTS idx_parliament_bills_title_trgm ON parliament_bills USING gin (title gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_parliament_bills_short_title_trgm ON parliament_bills USING gin (short_title gin_trgm_ops);

CREATE TABLE IF NOT EXISTS parliament_bill_events (
    event_id text PRIMARY KEY,
    bill_key text NOT NULL REFERENCES parliament_bills(bill_key) ON DELETE CASCADE,
    event_date date,
    chamber text,
    action text NOT NULL,
    source_site text,
    source_url text,
    documents jsonb NOT NULL DEFAULT '[]'::jsonb,
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_parliament_bill_events_bill_date ON parliament_bill_events (bill_key, event_date DESC);
CREATE INDEX IF NOT EXISTS idx_parliament_bill_events_action_trgm ON parliament_bill_events USING gin (action gin_trgm_ops);

UPDATE parliament_votes
SET bill_key = lower(bill_code) || '-' || bill_year::text || '-' || bill_number::text
WHERE bill_key IS NULL
  AND bill_code IS NOT NULL
  AND bill_number IS NOT NULL
  AND bill_year IS NOT NULL;

INSERT INTO parliament_bills (
    bill_key, source_id, source_site, bill_code, bill_number, bill_year,
    label, title, source_url, first_seen_at, last_seen_at, metadata
)
SELECT
    v.bill_key,
    (array_agg(v.source_id ORDER BY v.vote_time DESC))[1] AS source_id,
    (array_agg(v.metadata->>'site' ORDER BY v.vote_time DESC))[1] AS source_site,
    max(v.bill_code) AS bill_code,
    max(v.bill_number) AS bill_number,
    max(v.bill_year) AS bill_year,
    max(v.bill_code) || ' ' || max(v.bill_number)::text || '/' || max(v.bill_year)::text AS label,
    (array_agg(v.title ORDER BY v.vote_time DESC))[1] AS title,
    (array_remove(array_agg(v.bill_url ORDER BY v.vote_time DESC), NULL::text))[1] AS source_url,
    min(v.vote_time) AS first_seen_at,
    max(v.vote_time) AS last_seen_at,
    jsonb_build_object('source', 'parliament_votes_backfill') AS metadata
FROM parliament_votes v
WHERE v.bill_key IS NOT NULL
GROUP BY v.bill_key
ON CONFLICT (bill_key) DO NOTHING;

UPDATE parliament_bills pb
SET title = NULL,
    updated_at = now()
WHERE pb.title IS NOT NULL
  AND (pb.metadata->>'source' = 'parliament_votes_backfill' OR pb.source_url IS NULL)
  AND EXISTS (
      SELECT 1
      FROM parliament_votes v
      WHERE COALESCE(v.bill_key, lower(v.bill_code) || '-' || v.bill_year::text || '-' || v.bill_number::text) = pb.bill_key
        AND v.title = pb.title
  );

CREATE TABLE IF NOT EXISTS parliament_politicians (
    politician_key text PRIMARY KEY,
    display_name text NOT NULL,
    normalized_name text NOT NULL,
    family_name text,
    given_name text,
    first_chamber text,
    latest_chamber text,
    first_seen_at timestamptz NOT NULL DEFAULT now(),
    last_seen_at timestamptz NOT NULL DEFAULT now(),
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS idx_parliament_politicians_normalized ON parliament_politicians (normalized_name);

CREATE TABLE IF NOT EXISTS parliament_politician_summaries (
    politician_key text PRIMARY KEY REFERENCES parliament_politicians(politician_key) ON DELETE CASCADE,
    latest_party text,
    latest_party_key text,
    chambers text[] NOT NULL DEFAULT '{}'::text[],
    votes_recorded integer NOT NULL DEFAULT 0,
    present_votes integer NOT NULL DEFAULT 0,
    attendance_rate numeric,
    yes integer NOT NULL DEFAULT 0,
    no integer NOT NULL DEFAULT 0,
    abstain integer NOT NULL DEFAULT 0,
    not_voted integer NOT NULL DEFAULT 0,
    first_vote_time timestamptz,
    latest_vote_time timestamptz,
    refreshed_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_parliament_politician_summaries_latest_vote ON parliament_politician_summaries (latest_vote_time DESC);
CREATE INDEX IF NOT EXISTS idx_parliament_politician_summaries_attendance ON parliament_politician_summaries (attendance_rate DESC);

CREATE TABLE IF NOT EXISTS parliament_vote_positions (
    vote_id text NOT NULL REFERENCES parliament_votes(vote_id) ON DELETE CASCADE,
    politician_key text NOT NULL,
    politician_name text NOT NULL,
    family_name text,
    given_name text,
    party text,
    party_normalized text,
    vote_choice text NOT NULL,
    chamber text NOT NULL,
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (vote_id, politician_key)
);

ALTER TABLE parliament_vote_positions
ADD COLUMN IF NOT EXISTS party_normalized text;

CREATE INDEX IF NOT EXISTS idx_parliament_vote_positions_party ON parliament_vote_positions (party, vote_choice);
CREATE INDEX IF NOT EXISTS idx_parliament_vote_positions_party_normalized ON parliament_vote_positions (party_normalized, vote_choice);
CREATE INDEX IF NOT EXISTS idx_parliament_vote_positions_politician ON parliament_vote_positions (politician_key);
CREATE INDEX IF NOT EXISTS idx_parliament_vote_positions_vote_party_choice ON parliament_vote_positions (vote_id, party_normalized, vote_choice);
CREATE INDEX IF NOT EXISTS idx_parliament_vote_positions_party_vote ON parliament_vote_positions (party_normalized, vote_id);
CREATE INDEX IF NOT EXISTS idx_parliament_vote_positions_politician_vote ON parliament_vote_positions (politician_key, vote_id);

INSERT INTO schema_migrations (version)
VALUES ('0001_initial_contract')
ON CONFLICT (version) DO NOTHING;

INSERT INTO schema_migrations (version)
VALUES ('0002_parliament_votes')
ON CONFLICT (version) DO NOTHING;

INSERT INTO schema_migrations (version)
VALUES ('0003_parliament_politicians')
ON CONFLICT (version) DO NOTHING;

INSERT INTO schema_migrations (version)
VALUES ('0004_senat_votes')
ON CONFLICT (version) DO NOTHING;

INSERT INTO schema_migrations (version)
VALUES ('0005_parliament_bills')
ON CONFLICT (version) DO NOTHING;

INSERT INTO schema_migrations (version)
VALUES ('0006_civic_api_filters')
ON CONFLICT (version) DO NOTHING;

INSERT INTO schema_migrations (version)
VALUES ('0007_api_cache')
ON CONFLICT (version) DO NOTHING;

INSERT INTO schema_migrations (version)
VALUES ('0008_parliament_politician_summaries')
ON CONFLICT (version) DO NOTHING;
