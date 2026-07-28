-- envx v2.1 migration 005 — graph, review workflow, lifecycle, jobs.

-- ---------------------------------------------------------------- graph
-- Every edge records the document that justified it. A graph assertion
-- without provenance cannot be cited, so doc_id is NOT NULL by design.
CREATE TABLE IF NOT EXISTS graph_edges (
    edge_id      uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    source_id    text NOT NULL,
    target_id    text NOT NULL,
    relation     text NOT NULL,
    doc_id       uuid NOT NULL REFERENCES documents(doc_id) ON DELETE CASCADE,
    attributes   jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at   timestamptz NOT NULL DEFAULT now(),
    UNIQUE (source_id, target_id, relation, doc_id)
);
CREATE INDEX IF NOT EXISTS graph_edges_source ON graph_edges (source_id, relation);
CREATE INDEX IF NOT EXISTS graph_edges_target ON graph_edges (target_id, relation);
CREATE INDEX IF NOT EXISTS graph_edges_doc ON graph_edges (doc_id);

-- --------------------------------------------------------------- review
CREATE TABLE IF NOT EXISTS review_items (
    review_id      uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    doc_id         uuid NOT NULL REFERENCES documents(doc_id) ON DELETE CASCADE,
    state          text NOT NULL CHECK (state IN
                       ('trusted','usable_with_review','needs_reparse','needs_human_review')),
    triggers       text[] NOT NULL DEFAULT '{}',
    matter_active  boolean NOT NULL DEFAULT false,
    notes          text,
    created_at     timestamptz NOT NULL DEFAULT now(),
    resolved_at    timestamptz,
    resolved_by    text
);
CREATE INDEX IF NOT EXISTS review_items_open
    ON review_items (state) WHERE resolved_at IS NULL;
CREATE INDEX IF NOT EXISTS review_items_doc ON review_items (doc_id);

-- Append-only. No UPDATE, no DELETE — corrections supersede via the
-- supersedes column. Enforced by trigger below rather than convention.
CREATE TABLE IF NOT EXISTS corrections (
    correction_id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    doc_id                  uuid NOT NULL REFERENCES documents(doc_id) ON DELETE CASCADE,
    field_path              text NOT NULL,
    old_value               jsonb,
    new_value               jsonb,
    reason                  text NOT NULL,
    corrected_by            text NOT NULL,
    approved_by             text,
    affects_high_severity   boolean NOT NULL DEFAULT false,
    supersedes              uuid REFERENCES corrections(correction_id),
    created_at              timestamptz NOT NULL DEFAULT now(),
    -- §8 two-person rule: a high-severity change needs a distinct approver.
    CONSTRAINT two_person_review CHECK (
        NOT affects_high_severity
        OR (approved_by IS NOT NULL AND approved_by <> corrected_by)
    )
);
CREATE INDEX IF NOT EXISTS corrections_doc ON corrections (doc_id, created_at DESC);

CREATE OR REPLACE FUNCTION corrections_are_immutable() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'corrections is append-only; insert a superseding row instead';
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS corrections_no_mutate ON corrections;
CREATE TRIGGER corrections_no_mutate
    BEFORE UPDATE OR DELETE ON corrections
    FOR EACH ROW EXECUTE FUNCTION corrections_are_immutable();

-- ------------------------------------------------------------ lifecycle
CREATE TABLE IF NOT EXISTS document_lifecycle (
    doc_id                   uuid PRIMARY KEY REFERENCES documents(doc_id) ON DELETE CASCADE,
    storage_tier             text NOT NULL DEFAULT 'hot'
                                 CHECK (storage_tier IN ('hot','warm','cold')),
    tier_reason              text,
    matter_is_active         boolean NOT NULL DEFAULT false,
    last_queried_at          timestamptz,
    matter_closed_at         timestamptz,
    next_proceeding_at       timestamptz,
    embedding_model_version  text,
    evaluated_at             timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS document_lifecycle_tier ON document_lifecycle (storage_tier);

CREATE TABLE IF NOT EXISTS drift_findings (
    finding_id        uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    doc_id            uuid NOT NULL REFERENCES documents(doc_id) ON DELETE CASCADE,
    sampled_at        timestamptz NOT NULL DEFAULT now(),
    period            text,
    added_markers     text[] NOT NULL DEFAULT '{}',
    removed_markers   text[] NOT NULL DEFAULT '{}',
    is_regression     boolean NOT NULL DEFAULT false,
    detail            jsonb NOT NULL DEFAULT '{}'::jsonb
);
CREATE INDEX IF NOT EXISTS drift_findings_regressions
    ON drift_findings (sampled_at DESC) WHERE is_regression;

-- ----------------------------------------------------------------- jobs
CREATE TABLE IF NOT EXISTS jobs (
    job_id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    job_type         text NOT NULL,
    payload          jsonb NOT NULL,
    state            text NOT NULL DEFAULT 'pending'
                         CHECK (state IN ('pending','leased','done','failed','dead')),
    attempts         integer NOT NULL DEFAULT 0,
    max_attempts     integer NOT NULL DEFAULT 3,
    idempotency_key  text,
    leased_until     timestamptz,
    last_error       text,
    created_at       timestamptz NOT NULL DEFAULT now(),
    updated_at       timestamptz NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX IF NOT EXISTS jobs_idempotency
    ON jobs (job_type, idempotency_key) WHERE idempotency_key IS NOT NULL;
CREATE INDEX IF NOT EXISTS jobs_ready
    ON jobs (job_type, created_at) WHERE state IN ('pending','leased');
