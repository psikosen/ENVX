-- envx v2.1 migration 004 — retrieval indexes.
--
-- Vector stack note (revised mid-2026): the original design called for
-- pgvectorscale (StreamingDiskANN + SBQ). pgvectorscale has had effectively
-- no development in 2026 and should not be deployed new. This migration
-- targets plain pgvector, with VectorChord as the documented upgrade path
-- past ~50M vectors.
--
-- SECURITY: require pgvector >= 0.8.3. CVE-2026-3172 is a buffer overflow in
-- parallel HNSW index builds that can leak data from unrelated relations —
-- unacceptable in a multi-client corpus.
--
-- Full-text: pg_textsearch (PostgreSQL license) is preferred over pg_search
-- (AGPLv3) for a commercial legal product. Both provide real BM25; the
-- CREATE INDEX syntax differs, so the BM25 index is left commented with
-- both forms rather than guessing at deployment.

CREATE EXTENSION IF NOT EXISTS vector;

DO $$
BEGIN
    IF (SELECT extversion FROM pg_extension WHERE extname = 'vector') < '0.8.3' THEN
        RAISE WARNING
            'pgvector % is affected by CVE-2026-3172; upgrade to >= 0.8.3',
            (SELECT extversion FROM pg_extension WHERE extname = 'vector');
    END IF;
END $$;

-- Embeddings live in their own table rather than a column on blocks so that
-- cold-tier documents can drop vectors (§4.2) without rewriting block rows,
-- and so multiple model versions can coexist during a re-embed migration.
CREATE TABLE IF NOT EXISTS block_embeddings (
    block_id                 uuid NOT NULL REFERENCES blocks(block_id) ON DELETE CASCADE,
    embedding_model_version  text NOT NULL,
    embedding                vector(1024) NOT NULL,
    embedded_at              timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (block_id, embedding_model_version)
);

CREATE INDEX IF NOT EXISTS block_embeddings_hnsw
    ON block_embeddings USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);

CREATE INDEX IF NOT EXISTS block_embeddings_model
    ON block_embeddings (embedding_model_version);

-- BM25 over text_contextual. Pick one to match the installed extension:
--
--   pg_textsearch (Tiger Data, PostgreSQL license):
--     CREATE INDEX blocks_bm25_idx ON blocks
--       USING bm25 (block_id, text_contextual);
--
--   pg_search (ParadeDB, AGPLv3):
--     CREATE INDEX blocks_bm25_idx ON blocks
--       USING bm25 (block_id, text_contextual, client_id, matter_id, marker_array)
--       WITH (key_field='block_id');
--
-- Fallback so text search works before either extension is installed. This
-- is NOT BM25 — ts_rank is a different and worse ranking function — and must
-- be replaced before any production ranking claims are made.
CREATE INDEX IF NOT EXISTS blocks_tsv_fallback
    ON blocks USING gin (to_tsvector('english', coalesce(text_contextual, text_raw)));

-- Query-side lookups.
CREATE INDEX IF NOT EXISTS blocks_doc_page_idx ON blocks (doc_id, page_number);
CREATE INDEX IF NOT EXISTS blocks_region_idx ON blocks (region_id);
