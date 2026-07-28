-- envx v2.1 migration 001 — core document/page/block tables.
-- These are the baseline entities referenced by every preprocessing artifact.

CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE IF NOT EXISTS documents (
    doc_id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    sha256               bytea NOT NULL UNIQUE,
    client_id            text NOT NULL,
    matter_id            text,
    source_uri           text,
    original_filename    text,
    page_count           integer,
    language             text,
    doc_type             text,
    doc_type_confidence  real,
    ingest_run_id        uuid,
    superseded_by        uuid REFERENCES documents(doc_id),
    retention_policy     text,
    ingested_at          timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS documents_client_matter_idx
    ON documents (client_id, matter_id);
CREATE INDEX IF NOT EXISTS documents_doc_type_idx
    ON documents (doc_type);

CREATE TABLE IF NOT EXISTS pages (
    page_id                 uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    doc_id                  uuid NOT NULL REFERENCES documents(doc_id) ON DELETE CASCADE,
    page_number             integer NOT NULL,
    width_px                integer,
    height_px               integer,
    page_hash               bytea,
    native_text_coverage    real,
    cross_parser_agreement  real,
    roundtrip_score         real,
    region_count            integer DEFAULT 0,
    has_signature           boolean DEFAULT false,
    has_stamp               boolean DEFAULT false,
    has_handwriting         boolean DEFAULT false,
    UNIQUE (doc_id, page_number)
);
CREATE INDEX IF NOT EXISTS pages_doc_idx ON pages (doc_id, page_number);

CREATE TABLE IF NOT EXISTS blocks (
    block_id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    doc_id                    uuid NOT NULL REFERENCES documents(doc_id) ON DELETE CASCADE,
    page_number               integer NOT NULL,
    content_hash              bytea NOT NULL,
    text_raw                  text NOT NULL,
    text_contextual           text,
    region_id                 uuid,
    region_type               text,
    parse_run_id              uuid,
    client_id                 text NOT NULL,
    matter_id                 text,
    storage_tier              text NOT NULL DEFAULT 'hot'
        CHECK (storage_tier IN ('hot','warm','cold')),
    embedding_model_version   text,
    marker_array              text[] DEFAULT '{}',
    UNIQUE (doc_id, content_hash)
);
CREATE INDEX IF NOT EXISTS blocks_client_matter_tier_idx
    ON blocks (client_id, matter_id, storage_tier);
CREATE INDEX IF NOT EXISTS blocks_marker_gin ON blocks USING gin (marker_array);
