-- envx v2.1 migration 003 — markers and entity resolution.
-- Markers can now be derived from KIE extractions; entity_canonical resolves
-- "ACME Housing LLC" / "Acme Housing" / "ACME HOUSING L.L.C." to one identity.

CREATE TABLE IF NOT EXISTS entity_canonical (
    canonical_id      uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    entity_type       text NOT NULL,
    display_name      text NOT NULL,
    aliases           text[] NOT NULL DEFAULT '{}',
    normalized_key    text NOT NULL,
    attributes        jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at        timestamptz NOT NULL DEFAULT now(),
    UNIQUE (entity_type, normalized_key)
);

CREATE TABLE IF NOT EXISTS entities (
    entity_id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    doc_id                  uuid NOT NULL REFERENCES documents(doc_id) ON DELETE CASCADE,
    page_number             integer,
    region_id               uuid REFERENCES regions(region_id) ON DELETE SET NULL,
    entity_type             text NOT NULL,
    surface_form            text NOT NULL,
    canonical_id            uuid REFERENCES entity_canonical(canonical_id) ON DELETE SET NULL,
    resolution_confidence   real,
    source_extraction_id    uuid REFERENCES extracted_fields(extraction_id) ON DELETE SET NULL,
    extracted_by            text NOT NULL
        CHECK (extracted_by IN ('regex','ner_model','llm','kie_rule','human'))
);
CREATE INDEX IF NOT EXISTS entities_doc_idx ON entities (doc_id);
CREATE INDEX IF NOT EXISTS entities_canonical_idx ON entities (canonical_id);

CREATE TABLE IF NOT EXISTS markers (
    marker_id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    doc_id                 uuid NOT NULL REFERENCES documents(doc_id) ON DELETE CASCADE,
    block_id               uuid REFERENCES blocks(block_id) ON DELETE CASCADE,
    code                   text NOT NULL,
    confidence             real NOT NULL,
    extracted_by           text NOT NULL
        CHECK (extracted_by IN ('regex','ner_model','llm','kie_rule','human')),
    source_extraction_id   uuid REFERENCES extracted_fields(extraction_id) ON DELETE SET NULL,
    model_version          text,
    supersedes             uuid REFERENCES markers(marker_id),
    evidence               jsonb NOT NULL DEFAULT '{}'::jsonb,
    asserted_at            timestamptz NOT NULL DEFAULT now(),
    retracted_at           timestamptz
);
CREATE INDEX IF NOT EXISTS markers_doc_code_idx ON markers (doc_id, code);
CREATE INDEX IF NOT EXISTS markers_block_idx ON markers (block_id);
