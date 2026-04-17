-- envx v2.1 migration 002 — regions, schema library, extracted fields.
-- Adds the structures that turn GLM-OCR output into queryable SQL state.

CREATE TABLE IF NOT EXISTS regions (
    region_id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    doc_id            uuid NOT NULL REFERENCES documents(doc_id) ON DELETE CASCADE,
    page_number       integer NOT NULL,
    bbox              integer[] NOT NULL,
    region_type       text NOT NULL,
    label_confidence  real,
    parse_run_id      uuid,
    block_id          uuid REFERENCES blocks(block_id) ON DELETE SET NULL
);
CREATE INDEX IF NOT EXISTS regions_doc_page_idx ON regions (doc_id, page_number);
CREATE INDEX IF NOT EXISTS regions_type_idx ON regions (region_type);

CREATE TABLE IF NOT EXISTS doc_schemas (
    schema_id       text NOT NULL,
    version         text NOT NULL,
    json_schema     jsonb NOT NULL,
    content_hash    bytea NOT NULL,
    marker_rules    jsonb NOT NULL DEFAULT '[]'::jsonb,
    created_at      timestamptz NOT NULL DEFAULT now(),
    created_by      text,
    approved_by     text,
    PRIMARY KEY (schema_id, version)
);
CREATE INDEX IF NOT EXISTS doc_schemas_hash_idx ON doc_schemas (content_hash);

CREATE TABLE IF NOT EXISTS parse_attestations (
    attestation_id    uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    doc_id            uuid NOT NULL REFERENCES documents(doc_id) ON DELETE CASCADE,
    run_kind          text NOT NULL CHECK (run_kind IN ('parse','kie')),
    run_id            uuid NOT NULL,
    manifest          jsonb NOT NULL,
    signature         bytea NOT NULL,
    signer_key_id     text,
    created_at        timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS parse_attestations_doc_idx
    ON parse_attestations (doc_id, run_kind);

CREATE TABLE IF NOT EXISTS extracted_fields (
    extraction_id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    doc_id                uuid NOT NULL REFERENCES documents(doc_id) ON DELETE CASCADE,
    schema_id             text NOT NULL,
    schema_version        text NOT NULL,
    kie_run_id            uuid NOT NULL,
    field_path            text NOT NULL,
    field_value_text      text,
    field_value_num       numeric,
    field_value_date      date,
    field_value_json      jsonb,
    page_cited            integer,
    region_id             uuid REFERENCES regions(region_id) ON DELETE SET NULL,
    grounding_verified    boolean NOT NULL DEFAULT false,
    verification_score    real,
    extracted_at          timestamptz NOT NULL DEFAULT now(),
    FOREIGN KEY (schema_id, schema_version) REFERENCES doc_schemas(schema_id, version)
);
CREATE INDEX IF NOT EXISTS extracted_fields_doc_path_idx
    ON extracted_fields (doc_id, field_path);
CREATE INDEX IF NOT EXISTS extracted_fields_schema_path_value_idx
    ON extracted_fields (schema_id, field_path, field_value_text);
CREATE INDEX IF NOT EXISTS extracted_fields_json_gin
    ON extracted_fields USING gin (field_value_json);
